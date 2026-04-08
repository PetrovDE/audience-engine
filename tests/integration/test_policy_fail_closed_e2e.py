from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

from pipelines.minimal_slice import config

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "infra" / "docker-compose.dev.yml"
ENV_FILE = ROOT / "infra" / ".env"
ENV_EXAMPLE_FILE = ROOT / "infra" / ".env.example"


def _docker_available() -> bool:
    try:
        completed = subprocess.run(
            ["docker", "version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return completed.returncode == 0


def _ensure_env_file() -> None:
    if ENV_FILE.exists():
        return
    ENV_FILE.write_text(ENV_EXAMPLE_FILE.read_text(encoding="utf-8"), encoding="utf-8")


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        "docker",
        "compose",
        "--env-file",
        str(ENV_FILE),
        "-f",
        str(COMPOSE_FILE),
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if raw:
                rows.append(json.loads(raw))
    return rows


def _deterministic_vector(customer_id: str, dim: int = 8) -> list[float]:
    seed = sum(ord(c) for c in customer_id)
    return [((seed + i * 17) % 101) / 100.0 + 0.01 for i in range(dim)]


def _write_cpu_embeddings_for_run_flow(
    feature_mart_path: Path,
    output_path: Path = config.EMBEDDINGS_PATH,
    ollama_model: str = config.EMBEDDING_MODEL_VERSION,
) -> tuple[Path, int]:
    rows = _read_jsonl(feature_mart_path)
    prompt_version = "prompt_credit_v1"
    dim = 8
    emb_version = (
        f"{rows[0]['fs_version']}+{prompt_version}+{ollama_model}"
        if rows
        else "unknown"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in rows:
            payload = {
                "customer_id": row["customer_id"],
                "fs_version": row["fs_version"],
                "emb_version": emb_version,
                "policy_version": row["policy_version"],
                "vector": _deterministic_vector(row["customer_id"], dim=dim),
                "is_employee_flag": row["is_employee_flag"],
                "do_not_contact_flag": row["do_not_contact_flag"],
                "opt_out_flag": row.get("opt_out_flag", False),
                "legal_suppression_flag": row.get("legal_suppression_flag", False),
                "customer_tenure_months": row["customer_tenure_months"],
                "delinquency_12m_count": row["delinquency_12m_count"],
                "region_code": row.get("region_code", "unknown"),
                "segment_id": row.get("segment_id", "unknown"),
                "product_line": row.get("product_line", "unknown"),
            }
            f.write(json.dumps(payload) + "\n")
    return output_path, dim


def _postgres_conninfo() -> str:
    return (
        f"host={config.POSTGRES_HOST} "
        f"port={config.POSTGRES_PORT} "
        f"dbname={config.POSTGRES_DB} "
        f"user={config.POSTGRES_USER} "
        f"password={config.POSTGRES_PASSWORD}"
    )


def test_run_flow_fail_closed_persists_decisions_and_exports_zero(monkeypatch):
    if psycopg is None:
        pytest.skip("psycopg is not installed")
    from pipelines.minimal_slice import feature_mart, run_flow

    if not _docker_available():
        pytest.skip("docker is not available")
    _ensure_env_file()

    up = _compose("up", "-d", "postgres", "qdrant")
    if up.returncode != 0:
        pytest.skip(f"docker compose up failed: {up.stderr.strip()}")
    try:
        original_generate = run_flow.generate_synthetic_data

        def _generate_with_missing_required_input(customer_count: int, seed: int):
            generated = original_generate(customer_count=customer_count, seed=seed)
            Path(generated["comm_history"]).unlink(missing_ok=True)
            return generated

        monkeypatch.setattr(
            run_flow,
            "generate_synthetic_data",
            _generate_with_missing_required_input,
        )
        monkeypatch.setattr(
            run_flow,
            "build_embeddings",
            _write_cpu_embeddings_for_run_flow,
        )
        monkeypatch.setattr(
            run_flow,
            "create_or_replace_index",
            lambda embeddings_path, vector_size, collection_name, alias_name: {
                "alias": alias_name,
                "collection": collection_name,
            },
        )
        monkeypatch.setattr(
            run_flow,
            "retrieve_similar",
            lambda **kwargs: [
                {
                    "customer_id": "cust_00001",
                    "score": 0.91,
                    "payload": {
                        "do_not_contact_flag": False,
                        "is_employee_flag": False,
                        "customer_tenure_months": 12,
                        "delinquency_12m_count": 0,
                        "opt_out_flag": False,
                        "legal_suppression_flag": False,
                    },
                },
                {
                    "customer_id": "cust_00002",
                    "score": 0.77,
                    "payload": {
                        "do_not_contact_flag": False,
                        "is_employee_flag": False,
                        "customer_tenure_months": 9,
                        "delinquency_12m_count": 1,
                        "opt_out_flag": False,
                        "legal_suppression_flag": False,
                    },
                },
            ],
        )
        monkeypatch.setattr(run_flow, "minio_is_configured", lambda: False)
        monkeypatch.setattr(feature_mart, "minio_is_configured", lambda: False)

        summary = run_flow.run_minimal_vertical_slice(
            campaign_id="camp_fail_closed_e2e"
        )
        run_id = summary["versions"]["run_id"]
        export_path = Path(summary["export_path"])
        exported_rows = _read_jsonl(export_path) if export_path.exists() else []

        assert summary["policy"]["status"] == "failed_closed"
        assert summary["policy"]["approved_count"] == 0
        assert len(exported_rows) == 0

        with psycopg.connect(_postgres_conninfo()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT customer_id, decision, reason_codes
                    FROM policy_decision_audit
                    WHERE run_id = %s::uuid
                    """,
                    (run_id,),
                )
                decision_rows = cur.fetchall()

        assert len(decision_rows) == summary["retrieval"]["retrieved_count"]
        assert len(decision_rows) > 0
        assert all(row[1] == "reject" for row in decision_rows)
        assert all(
            "POLICY_FAIL_CLOSED_REQUIRED_INPUT" in (row[2] or [])
            for row in decision_rows
        )
    finally:
        _compose("down")
