from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

from pipelines.minimal_slice import config
from pipelines.minimal_slice.exporter import export_approved
from pipelines.minimal_slice.feature_mart import build_feature_mart_snapshot
from pipelines.minimal_slice.policy_engine import evaluate_policy
from pipelines.minimal_slice.qdrant_index import (
    build_generation,
    promote_alias,
    validate_generation,
)
from pipelines.minimal_slice.retrieval import retrieve_similar
from pipelines.minimal_slice.synthetic_data import generate_synthetic_data


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
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _deterministic_vector(customer_id: str, dim: int = 8) -> list[float]:
    seed = sum(ord(c) for c in customer_id)
    return [((seed + i * 17) % 101) / 100.0 + 0.01 for i in range(dim)]


def _write_cpu_embeddings(feature_mart_path: Path, output_path: Path) -> tuple[Path, int]:
    rows = _read_jsonl(feature_mart_path)
    dim = 8
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in rows:
            payload = {
                "customer_id": row["customer_id"],
                "fs_version": row["fs_version"],
                "emb_version": "fs_credit_v1+prompt_credit_v1+cpu-mock-embed-v1",
                "policy_version": row["policy_version"],
                "vector": _deterministic_vector(row["customer_id"], dim=dim),
                "is_employee_flag": row["is_employee_flag"],
                "do_not_contact_flag": row["do_not_contact_flag"],
                "opt_out_flag": row.get("opt_out_flag", False),
                "legal_suppression_flag": row.get("legal_suppression_flag", False),
                "customer_tenure_months": row["customer_tenure_months"],
                "delinquency_12m_count": row["delinquency_12m_count"],
                "region_code": row["region_code"],
                "segment_id": row["segment_id"],
                "product_line": row["product_line"],
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


def _write_and_verify_audit_records(
    *,
    run_id: str,
    campaign_id: str,
    version_bundle: dict,
    selected: list[dict],
    rejection_summary: dict,
) -> None:
    with psycopg.connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audience_run (
                    run_id,
                    campaign_id,
                    product_id,
                    run_ts,
                    version_bundle,
                    parameters
                ) VALUES (%s, %s, %s, now(), %s::jsonb, %s::jsonb)
                """,
                (
                    run_id,
                    campaign_id,
                    "integration_smoke_cpu",
                    json.dumps(version_bundle),
                    json.dumps({"smoke": True}),
                ),
            )
            for rank, row in enumerate(selected, start=1):
                cur.execute(
                    """
                    INSERT INTO audience_run_selected (
                        run_id,
                        customer_id,
                        final_score,
                        rank,
                        channel,
                        selected_ts
                    ) VALUES (%s, %s, %s, %s, %s, now())
                    """,
                    (
                        run_id,
                        row["customer_id"],
                        float(row.get("score", 0.0)),
                        rank,
                        "email",
                    ),
                )
            for reason_code, rejected_count in rejection_summary.items():
                cur.execute(
                    """
                    INSERT INTO audience_run_rejections_summary (
                        run_id,
                        reason_code,
                        rejected_count,
                        summary_ts
                    ) VALUES (%s, %s, %s, now())
                    """,
                    (run_id, reason_code, int(rejected_count)),
                )

            cur.execute("SELECT count(*) FROM audience_run WHERE run_id = %s", (run_id,))
            run_count = int(cur.fetchone()[0])
            cur.execute(
                "SELECT count(*) FROM audience_run_selected WHERE run_id = %s", (run_id,)
            )
            selected_count = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT count(*) FROM audience_run_rejections_summary
                WHERE run_id = %s
                """,
                (run_id,),
            )
            rejection_count = int(cur.fetchone()[0])
        conn.commit()

    assert run_count == 1
    assert selected_count == len(selected)
    assert rejection_count == len(rejection_summary)


def test_minimal_slice_smoke_cpu_no_gpu_required():
    if psycopg is None:
        pytest.skip("psycopg is not installed")
    if not _docker_available():
        pytest.skip("docker is not available")
    _ensure_env_file()

    up = _compose("up", "-d", "postgres", "qdrant")
    if up.returncode != 0:
        pytest.skip(f"docker compose up failed: {up.stderr.strip()}")
    try:
        # seed
        generate_synthetic_data(customer_count=120, seed=7)

        # build generation from CPU-friendly deterministic vectors
        feature_mart_path = build_feature_mart_snapshot(raw_path=config.RAW_PATH)
        embeddings_path, vector_size = _write_cpu_embeddings(
            feature_mart_path=feature_mart_path,
            output_path=config.EMBEDDINGS_PATH,
        )
        collection_name = f"audience-smoke-{uuid.uuid4().hex[:8]}"
        build_meta = build_generation(
            embeddings_path=embeddings_path,
            vector_size=vector_size,
            alias_name_override=config.QDRANT_ALIAS,
            collection_name_override=collection_name,
            emb_version="fs_credit_v1+prompt_credit_v1+cpu-mock-embed-v1",
        )

        # validate and promote
        validate_generation(
            embeddings_path=embeddings_path,
            collection_name=build_meta["collection"],
            alias_name=build_meta["alias"],
            expected_count=build_meta["points_count"],
        )
        promote_alias(alias_name=build_meta["alias"], collection_name=build_meta["collection"])

        # recommend -> policy -> export
        retrieved = retrieve_similar(
            top_k=30,
            query_customer_id="cust_00000",
            product_line="credit_card",
            region_codes=["us_west", "us_central", "us_east"],
            segment_ids=["mass", "affluent", "student", "smb"],
            min_tenure_months=3,
            max_delinquency_12m_count=2,
            fs_version="fs_credit_v1",
            emb_version="fs_credit_v1+prompt_credit_v1+cpu-mock-embed-v1",
            policy_version=config.POLICY_VERSION,
        )
        policy_input = [
            {
                "customer_id": row["customer_id"],
                "score": row.get("score", 0.0),
                "do_not_contact_flag": row.get("payload", {}).get(
                    "do_not_contact_flag", False
                ),
                "is_employee_flag": row.get("payload", {}).get("is_employee_flag", False),
                "customer_tenure_months": row.get("payload", {}).get(
                    "customer_tenure_months", 0
                ),
                "delinquency_12m_count": row.get("payload", {}).get(
                    "delinquency_12m_count", 0
                ),
                "opt_out_flag": row.get("payload", {}).get("opt_out_flag", False),
                "legal_suppression_flag": row.get("payload", {}).get(
                    "legal_suppression_flag", False
                ),
            }
            for row in retrieved
            if row.get("customer_id")
        ]
        policy_result = evaluate_policy(
            candidates=policy_input,
            policy_version=config.POLICY_VERSION,
            blacklist_path=config.BLACKLIST_PATH,
            comm_history_path=config.COMM_HISTORY_PATH,
            campaign_id="smoke-campaign",
            requested_size=20,
        )
        export_approved(policy_result=policy_result, output_path=config.EXPORT_PATH)

        # audit verify
        run_id = str(uuid.uuid4())
        version_bundle = {
            "fs_version": "fs_credit_v1",
            "emb_version": "fs_credit_v1+prompt_credit_v1+cpu-mock-embed-v1",
            "policy_version": config.POLICY_VERSION,
            "index_alias": config.QDRANT_ALIAS,
            "concrete_qdrant_collection": build_meta["collection"],
            "run_id": run_id,
            "campaign_id": "smoke-campaign",
        }
        _write_and_verify_audit_records(
            run_id=run_id,
            campaign_id="smoke-campaign",
            version_bundle=version_bundle,
            selected=policy_result.get("selected", []),
            rejection_summary=policy_result.get("rejection_summary", {}),
        )
    finally:
        _compose("down")


def test_minimal_slice_smoke_gpu_optional():
    if psycopg is None:
        pytest.skip("psycopg is not installed")
    if os.getenv("SKIP_GPU_TESTS", "1") == "1":
        pytest.skip("SKIP_GPU_TESTS=1")
    if not _docker_available():
        pytest.skip("docker is not available")
    _ensure_env_file()

    up = _compose("up", "-d")
    if up.returncode != 0:
        pytest.skip(f"docker compose up failed: {up.stderr.strip()}")
    try:
        run = subprocess.run(
            ["python", "-m", "pipelines.minimal_slice.run_flow"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(ROOT),
        )
        assert run.returncode == 0, run.stderr
    finally:
        _compose("down")
