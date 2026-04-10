from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from hashlib import sha256
from pathlib import Path
from urllib import request as urllib_request

import pytest
import yaml
from fastapi.testclient import TestClient

try:
    import clickhouse_connect  # noqa: F401
except ImportError:  # pragma: no cover
    clickhouse_connect = None

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

from pipelines.minimal_slice import config as minimal_config
from pipelines.minimal_slice import (
    delivery_runner,
    delivery_store,
    export_table,
    feature_mart,
    lifecycle_audit,
    qdrant_index,
    retrieval,
    run_flow,
    storage,
)
from services.retrieval_api import app as retrieval_api_app

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "infra" / "docker-compose.dev.yml"
ENV_FILE = ROOT / "infra" / ".env"
ENV_EXAMPLE_FILE = ROOT / "infra" / ".env.example"
CLICKHOUSE_SCHEMA_SQL = (
    ROOT / "infra" / "clickhouse" / "sql" / "001_feature_mart_snapshot.sql"
)
EXPORT_STAGING_MIGRATION_SQL = (
    ROOT / "infra" / "postgres" / "migrations" / "005_export_staging.sql"
)
DELIVERY_LAYER_MIGRATION_SQL = (
    ROOT / "infra" / "postgres" / "migrations" / "006_delivery_layer.sql"
)
DELIVERY_STATUS_MIGRATION_SQL = (
    ROOT / "infra" / "postgres" / "migrations" / "007_delivery_status_no_source_rows.sql"
)
SERVICE_PORTS = {
    "postgres": 5432,
    "clickhouse": 8123,
    "qdrant": 6333,
}


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


def _running_services() -> set[str]:
    result = _compose("ps", "--status", "running", "--services")
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _prefer_stack_preservation() -> bool:
    return os.getenv("AE_E2E_PRESERVE_STACK", "1").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _primary_host_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _parse_endpoint(raw: str) -> tuple[str, int]:
    value = raw.strip()
    if value.startswith("[") and "]:" in value:
        host, port_s = value[1:].split("]:", 1)
        return host, int(port_s)
    if ":" in value:
        host, port_s = value.rsplit(":", 1)
        return host, int(port_s)
    raise ValueError(f"Could not parse docker compose port output: {raw!r}")


def _normalize_endpoint_host(host: str) -> str:
    token = host.strip().lower()
    if token in {"0.0.0.0", "::", "[::]", ""}:
        # Avoid localhost ambiguity on Windows where loopback-only services may
        # shadow the docker-published listener on the same numeric port.
        return _primary_host_ip()
    if token == "localhost":
        return "127.0.0.1"
    return host


def _compose_endpoint(service: str, container_port: int) -> tuple[str, int]:
    result = _compose("port", service, str(container_port))
    if result.returncode != 0:
        raise RuntimeError(
            f"docker compose port failed for {service}:{container_port}: "
            f"{result.stderr.strip()}"
        )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(
            f"docker compose port returned no mapping for {service}:{container_port}"
        )

    parsed = [_parse_endpoint(line) for line in lines]
    for host, port in parsed:
        normalized = _normalize_endpoint_host(host)
        if normalized not in {"127.0.0.1", "::1"}:
            return normalized, port
    host, port = parsed[0]
    return _normalize_endpoint_host(host), port


def _required_endpoints() -> dict[str, tuple[str, int]]:
    return {
        service: _compose_endpoint(service, container_port)
        for service, container_port in SERVICE_PORTS.items()
    }


def _clickhouse_client(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [
        "docker",
        "compose",
        "--env-file",
        str(ENV_FILE),
        "-f",
        str(COMPOSE_FILE),
        "exec",
        "-T",
        "clickhouse",
        "clickhouse-client",
        "--user",
        "audience_engine",
        "--password",
        "change_me",
        "--database",
        "audience_engine",
        *args,
    ]

    kwargs = {
        "text": True,
        "capture_output": True,
    }
    if input_text is not None:
        kwargs["input"] = input_text

    return subprocess.run(cmd, **kwargs)


def _wait_for_postgres_ready(
    host: str,
    port: int,
    timeout_seconds: float = 45.0,
) -> bool:
    if psycopg is None:
        return False
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with psycopg.connect(_postgres_conninfo(host=host, port=port)):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def _wait_for_clickhouse_ready(timeout_seconds: float = 45.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        probe = _clickhouse_client("--query", "SELECT 1")
        if probe.returncode == 0:
            return True
        time.sleep(0.5)
    return False


def _wait_for_qdrant_ready(
    *, host: str, port: int, timeout_seconds: float = 45.0
) -> bool:
    deadline = time.time() + timeout_seconds
    url = f"http://{host}:{port}/collections"
    while time.time() < deadline:
        try:
            with urllib_request.urlopen(url, timeout=2) as resp:
                if int(resp.status) == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


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


def _embedding_prompt_version() -> str:
    with minimal_config.EMBED_SPEC_PATH.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    return str(payload["composition"]["prompt_version"])


def _write_cpu_embeddings_for_run_flow(
    feature_mart_path: Path,
    output_path: Path = minimal_config.EMBEDDINGS_PATH,
    ollama_model: str = minimal_config.EMBEDDING_MODEL_VERSION,
) -> tuple[Path, int]:
    rows = _read_jsonl(feature_mart_path)
    prompt_version = _embedding_prompt_version()
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


def _postgres_conninfo(*, host: str, port: int) -> str:
    return (
        f"host={host} "
        f"port={port} "
        "dbname=audience_engine "
        "user=audience_engine "
        "password=change_me"
    )


def _seed_clickhouse_feature_slice() -> None:
    schema_sql = CLICKHOUSE_SCHEMA_SQL.read_text(encoding="utf-8")
    create = _clickhouse_client("--multiquery", input_text=schema_sql)
    assert create.returncode == 0, create.stderr

    truncate = _clickhouse_client("--query", "TRUNCATE TABLE feature_mart_snapshot")
    assert truncate.returncode == 0, truncate.stderr

    insert_sql = """
    INSERT INTO feature_mart_snapshot (
        customer_id, fs_version, policy_version, customer_age_years,
        customer_tenure_months, credit_score_band, delinquency_12m_count,
        utilization_ratio_avg_3m, card_spend_total_3m, digital_engagement_score,
        is_employee_flag, do_not_contact_flag, opt_out_flag, legal_suppression_flag,
        region_code, segment_id, product_line
    ) VALUES
        ('cust_00000','fs_credit_v1','policy_credit_v1',35,24,'A',0,0.21,1800,0.88,0,0,0,0,'us_west','mass','credit_card'),
        ('cust_ch_001','fs_credit_v1','policy_credit_v1',42,48,'A',0,0.17,2200,0.91,0,0,0,0,'us_east','affluent','credit_card'),
        ('cust_ch_002','fs_credit_v1','policy_credit_v1',29,18,'B',1,0.33,950,0.73,0,0,0,0,'us_central','mass','credit_card'),
        ('cust_ch_003','fs_credit_v1','policy_credit_v1',31,15,'B',0,0.27,1200,0.69,0,0,0,0,'us_west','student','credit_card'),
        ('cust_ch_004','fs_credit_v1','policy_credit_v1',55,72,'A',0,0.14,3400,0.84,0,0,0,0,'us_east','smb','credit_card');
    """
    insert = _clickhouse_client("--query", insert_sql)
    assert insert.returncode == 0, insert.stderr


def _ensure_delivery_tables(*, postgres_host: str, postgres_port: int) -> None:
    conninfo = _postgres_conninfo(host=postgres_host, port=postgres_port)
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.audience_export_staging')")
            existing = cur.fetchone()
            if not (existing and existing[0]):
                cur.execute(EXPORT_STAGING_MIGRATION_SQL.read_text(encoding="utf-8"))
            cur.execute(DELIVERY_LAYER_MIGRATION_SQL.read_text(encoding="utf-8"))
            cur.execute(DELIVERY_STATUS_MIGRATION_SQL.read_text(encoding="utf-8"))
        conn.commit()


def _configure_live_runtime(
    *,
    monkeypatch,
    postgres_host: str,
    postgres_port: int,
    clickhouse_host: str,
    clickhouse_port: int,
    qdrant_host: str,
    qdrant_port: int,
) -> None:
    monkeypatch.setattr(storage.config, "CLICKHOUSE_HOST", clickhouse_host)
    monkeypatch.setattr(storage.config, "CLICKHOUSE_PORT", clickhouse_port)
    monkeypatch.setattr(storage.config, "CLICKHOUSE_DB", "audience_engine")
    monkeypatch.setattr(storage.config, "CLICKHOUSE_USER", "audience_engine")
    monkeypatch.setattr(storage.config, "CLICKHOUSE_PASSWORD", "change_me")
    monkeypatch.setattr(
        storage.config,
        "CLICKHOUSE_FEATURE_SLICE_QUERY",
        (
            "SELECT customer_id, fs_version, policy_version, customer_age_years, "
            "customer_tenure_months, credit_score_band, delinquency_12m_count, "
            "utilization_ratio_avg_3m, card_spend_total_3m, "
            "digital_engagement_score, is_employee_flag, do_not_contact_flag, "
            "opt_out_flag, legal_suppression_flag, region_code, segment_id, "
            "product_line FROM feature_mart_snapshot ORDER BY customer_id"
        ),
    )
    monkeypatch.setattr(storage.config, "CLICKHOUSE_FEATURE_SLICE_LIMIT", 100)

    monkeypatch.setattr(run_flow, "POSTGRES_HOST", postgres_host)
    monkeypatch.setattr(run_flow, "POSTGRES_PORT", postgres_port)
    monkeypatch.setattr(run_flow, "POSTGRES_DB", "audience_engine")
    monkeypatch.setattr(run_flow, "POSTGRES_USER", "audience_engine")
    monkeypatch.setattr(run_flow, "POSTGRES_PASSWORD", "change_me")
    monkeypatch.setattr(qdrant_index, "POSTGRES_HOST", postgres_host)
    monkeypatch.setattr(qdrant_index, "POSTGRES_PORT", postgres_port)
    monkeypatch.setattr(qdrant_index, "POSTGRES_DB", "audience_engine")
    monkeypatch.setattr(qdrant_index, "POSTGRES_USER", "audience_engine")
    monkeypatch.setattr(qdrant_index, "POSTGRES_PASSWORD", "change_me")
    monkeypatch.setattr(lifecycle_audit, "POSTGRES_HOST", postgres_host)
    monkeypatch.setattr(lifecycle_audit, "POSTGRES_PORT", postgres_port)
    monkeypatch.setattr(lifecycle_audit, "POSTGRES_DB", "audience_engine")
    monkeypatch.setattr(lifecycle_audit, "POSTGRES_USER", "audience_engine")
    monkeypatch.setattr(lifecycle_audit, "POSTGRES_PASSWORD", "change_me")
    monkeypatch.setattr(qdrant_index, "QDRANT_URL", f"http://{qdrant_host}:{qdrant_port}")
    monkeypatch.setattr(retrieval, "QDRANT_URL", f"http://{qdrant_host}:{qdrant_port}")

    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_HOST", postgres_host)
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_PORT", postgres_port)
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_DB", "audience_engine")
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_USER", "audience_engine")
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_PASSWORD", "change_me")
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_SCHEMA", "public")
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_TABLE", "audience_export_staging")
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_SSLMODE", "")
    monkeypatch.setattr(delivery_store, "POSTGRES_HOST", postgres_host)
    monkeypatch.setattr(delivery_store, "POSTGRES_PORT", postgres_port)
    monkeypatch.setattr(delivery_store, "POSTGRES_DB", "audience_engine")
    monkeypatch.setattr(delivery_store, "POSTGRES_USER", "audience_engine")
    monkeypatch.setattr(delivery_store, "POSTGRES_PASSWORD", "change_me")
    monkeypatch.setattr(delivery_store, "POSTGRES_SSLMODE", "")

    monkeypatch.setattr(feature_mart, "minio_is_configured", lambda: False)
    monkeypatch.setattr(run_flow, "build_embeddings", _write_cpu_embeddings_for_run_flow)


def test_clickhouse_postgres_export_profile_live_e2e(monkeypatch):
    if psycopg is None:
        pytest.skip("psycopg is not installed")
    if clickhouse_connect is None:
        pytest.skip("clickhouse-connect is not installed")
    if not _docker_available():
        pytest.skip("docker is not available")

    _ensure_env_file()
    required = {"postgres", "clickhouse", "qdrant"}
    running_before = _running_services()
    started_by_test = required - running_before
    if started_by_test:
        up = _compose("up", "-d", *sorted(started_by_test))
        if up.returncode != 0:
            pytest.skip(f"docker compose up failed: {up.stderr.strip()}")

    try:
        endpoints = _required_endpoints()
        pg_host, pg_port = endpoints["postgres"]
        ch_host, ch_port = endpoints["clickhouse"]
        qdrant_host, qdrant_port = endpoints["qdrant"]

        if not _wait_for_postgres_ready(host=pg_host, port=pg_port):
            pytest.skip("postgres did not become ready in time")
        if not _wait_for_clickhouse_ready():
            pytest.skip("clickhouse did not become ready in time")
        if not _wait_for_qdrant_ready(host=qdrant_host, port=qdrant_port):
            pytest.skip("qdrant did not become ready in time")

        _ensure_delivery_tables(postgres_host=pg_host, postgres_port=pg_port)
        _seed_clickhouse_feature_slice()

        _configure_live_runtime(
            monkeypatch=monkeypatch,
            postgres_host=pg_host,
            postgres_port=pg_port,
            clickhouse_host=ch_host,
            clickhouse_port=ch_port,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
        )

        summary = run_flow.run_minimal_vertical_slice(
            campaign_id="camp_clickhouse_postgres_e2e",
            policy_version="policy_credit_v1",
            integration_profile_id="clickhouse_postgres_export",
            delivery_target_id="crm_postgres_outbox",
            requested_size=3,
        )

        assert summary["status"] == "ok"
        assert summary["operations"]["source_id"] == "clickhouse_feature_slice"
        assert summary["operations"]["export_id"] == "postgres_export_table"
        assert summary["operations"]["delivery_target_id"] == "crm_postgres_outbox"
        assert summary["export"]["rows_written"] >= 1
        assert summary["delivery"]["status"] == "delivered"
        assert summary["delivery"]["rows_delivered"] >= 1

        feature_mart_rows = _read_jsonl(Path(summary["inputs"]["feature_mart_path"]))
        feature_mart_ids = {row["customer_id"] for row in feature_mart_rows}
        assert "cust_ch_001" in feature_mart_ids
        assert "cust_ch_004" in feature_mart_ids

        run_id = summary["versions"]["run_id"]
        with psycopg.connect(_postgres_conninfo(host=pg_host, port=pg_port)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        run_id::text,
                        campaign_id,
                        customer_id,
                        policy_version,
                        integration_profile_id,
                        source_id,
                        export_target_id,
                        export_context
                    FROM audience_export_staging
                    WHERE run_id = %s::uuid
                    ORDER BY rank
                    """,
                    (run_id,),
                )
                staging_rows = cur.fetchall()

        assert len(staging_rows) >= 1
        for row in staging_rows:
            assert row[0] == run_id
            assert row[1] == "camp_clickhouse_postgres_e2e"
            assert row[2]
            assert row[3] == "policy_credit_v1"
            assert row[4] == "clickhouse_postgres_export"
            assert row[5] == "clickhouse_feature_slice"
            assert row[6] == "postgres_export_table"
            assert isinstance(row[7], dict)
            assert isinstance(row[7].get("reason_codes", []), list)

        with psycopg.connect(_postgres_conninfo(host=pg_host, port=pg_port)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        run_id::text,
                        campaign_id,
                        customer_id,
                        delivery_target_id,
                        outbox_status,
                        policy_version,
                        integration_profile_id,
                        source_id,
                        export_target_id,
                        payload
                    FROM audience_crm_postgres_outbox
                    WHERE run_id = %s::uuid
                    ORDER BY customer_id
                    """,
                    (run_id,),
                )
                outbox_rows = cur.fetchall()
                cur.execute(
                    """
                    SELECT
                        run_id::text,
                        customer_id,
                        delivery_target_id,
                        delivery_status,
                        policy_version,
                        integration_profile_id,
                        source_id,
                        export_target_id
                    FROM audience_delivery_record
                    WHERE run_id = %s::uuid
                    ORDER BY customer_id
                    """,
                    (run_id,),
                )
                delivery_rows = cur.fetchall()
                cur.execute(
                    """
                    SELECT status
                    FROM audience_delivery_job
                    WHERE run_id = %s::uuid
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (run_id,),
                )
                latest_job_status = cur.fetchone()[0]
                cur.execute(
                    """
                    SELECT attempt_status
                    FROM audience_delivery_attempt
                    WHERE run_id = %s::uuid
                    ORDER BY attempt_ts ASC, id ASC
                    """,
                    (run_id,),
                )
                attempt_statuses = [r[0] for r in cur.fetchall()]

        assert len(outbox_rows) >= 1
        assert len(delivery_rows) == len(outbox_rows)
        assert latest_job_status == "delivered"
        assert attempt_statuses[:2] == ["pending", "materialized"]
        assert attempt_statuses[-1] == "delivered"

        for row in outbox_rows:
            assert row[0] == run_id
            assert row[1] == "camp_clickhouse_postgres_e2e"
            assert row[3] == "crm_postgres_outbox"
            assert row[4] == "pending"
            assert row[5] == "policy_credit_v1"
            assert row[6] == "clickhouse_postgres_export"
            assert row[7] == "clickhouse_feature_slice"
            assert row[8] == "postgres_export_table"
            assert isinstance(row[9], dict)

        for row in delivery_rows:
            assert row[0] == run_id
            assert row[2] == "crm_postgres_outbox"
            assert row[3] == "delivered"
            assert row[4] == "policy_credit_v1"
            assert row[5] == "clickhouse_postgres_export"
            assert row[6] == "clickhouse_feature_slice"
            assert row[7] == "postgres_export_table"

        second_delivery = delivery_runner.execute_delivery_for_run(
            run_id=run_id,
            delivery_target_id="crm_postgres_outbox",
            trigger_source="integration:test",
            requested_by_role="system_internal",
            requested_by_id="system:test",
        )
        assert second_delivery["status"] == "skipped_conflict"
        assert second_delivery["rows_delivered"] == 0
        assert second_delivery["rows_skipped_conflict"] == len(outbox_rows)

        with psycopg.connect(_postgres_conninfo(host=pg_host, port=pg_port)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*)
                    FROM audience_crm_postgres_outbox
                    WHERE run_id = %s::uuid
                    """,
                    (run_id,),
                )
                outbox_count_after_retry = int(cur.fetchone()[0])
        assert outbox_count_after_retry == len(outbox_rows)
    finally:
        if started_by_test and not _prefer_stack_preservation():
            _compose("stop", *sorted(started_by_test))


def test_clickhouse_postgres_csv_delivery_retry_keeps_immutable_artifacts(monkeypatch):
    if psycopg is None:
        pytest.skip("psycopg is not installed")
    if clickhouse_connect is None:
        pytest.skip("clickhouse-connect is not installed")
    if not _docker_available():
        pytest.skip("docker is not available")

    _ensure_env_file()
    required = {"postgres", "clickhouse", "qdrant"}
    running_before = _running_services()
    started_by_test = required - running_before
    if started_by_test:
        up = _compose("up", "-d", *sorted(started_by_test))
        if up.returncode != 0:
            pytest.skip(f"docker compose up failed: {up.stderr.strip()}")

    try:
        endpoints = _required_endpoints()
        pg_host, pg_port = endpoints["postgres"]
        ch_host, ch_port = endpoints["clickhouse"]
        qdrant_host, qdrant_port = endpoints["qdrant"]

        if not _wait_for_postgres_ready(host=pg_host, port=pg_port):
            pytest.skip("postgres did not become ready in time")
        if not _wait_for_clickhouse_ready():
            pytest.skip("clickhouse did not become ready in time")
        if not _wait_for_qdrant_ready(host=qdrant_host, port=qdrant_port):
            pytest.skip("qdrant did not become ready in time")

        _ensure_delivery_tables(postgres_host=pg_host, postgres_port=pg_port)
        _seed_clickhouse_feature_slice()
        _configure_live_runtime(
            monkeypatch=monkeypatch,
            postgres_host=pg_host,
            postgres_port=pg_port,
            clickhouse_host=ch_host,
            clickhouse_port=ch_port,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
        )

        summary = run_flow.run_minimal_vertical_slice(
            campaign_id="camp_clickhouse_csv_e2e",
            policy_version="policy_credit_v1",
            integration_profile_id="clickhouse_postgres_export",
            delivery_target_id="crm_csv_file",
            requested_size=3,
        )
        assert summary["status"] == "ok"
        assert summary["delivery"]["status"] == "delivered"

        run_id = summary["versions"]["run_id"]
        first_job_id = summary["delivery"]["delivery_job_id"]
        first_artifact = Path(str(summary["delivery"]["artifact_uri"]))
        assert first_artifact.exists()
        assert f"run_id={run_id}" in str(first_artifact)
        assert f"delivery_job_id={first_job_id}" in str(first_artifact)
        first_hash_before_retry = sha256(first_artifact.read_bytes()).hexdigest()
        first_rows_delivered = int(summary["delivery"]["rows_delivered"])

        second_delivery = delivery_runner.execute_delivery_for_run(
            run_id=run_id,
            delivery_target_id="crm_csv_file",
            trigger_source="integration:test",
            requested_by_role="system_internal",
            requested_by_id="system:test",
        )
        assert second_delivery["status"] == "skipped_conflict"
        assert second_delivery["rows_delivered"] == 0
        assert second_delivery["rows_skipped_conflict"] == first_rows_delivered

        second_job_id = second_delivery["delivery_job_id"]
        second_artifact = Path(str(second_delivery["artifact_uri"]))
        assert second_artifact.exists()
        assert second_artifact != first_artifact
        assert f"delivery_job_id={second_job_id}" in str(second_artifact)
        assert sha256(first_artifact.read_bytes()).hexdigest() == first_hash_before_retry

        with psycopg.connect(_postgres_conninfo(host=pg_host, port=pg_port)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT delivery_job_id::text, count(*)
                    FROM audience_delivery_record
                    WHERE run_id = %s::uuid AND delivery_target_id = 'crm_csv_file'
                    GROUP BY delivery_job_id
                    ORDER BY delivery_job_id::text
                    """,
                    (run_id,),
                )
                grouped = cur.fetchall()
                cur.execute(
                    """
                    SELECT status
                    FROM audience_delivery_job
                    WHERE run_id = %s::uuid AND delivery_target_id = 'crm_csv_file'
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (run_id,),
                )
                latest_status = str(cur.fetchone()[0])
        assert grouped == [(first_job_id, first_rows_delivered)]
        assert latest_status == "skipped_conflict"
    finally:
        if started_by_test and not _prefer_stack_preservation():
            _compose("stop", *sorted(started_by_test))


def test_retrieval_admin_delivery_endpoints_are_db_backed(monkeypatch):
    if psycopg is None:
        pytest.skip("psycopg is not installed")
    if clickhouse_connect is None:
        pytest.skip("clickhouse-connect is not installed")
    if not _docker_available():
        pytest.skip("docker is not available")

    _ensure_env_file()
    required = {"postgres", "clickhouse", "qdrant"}
    running_before = _running_services()
    started_by_test = required - running_before
    if started_by_test:
        up = _compose("up", "-d", *sorted(started_by_test))
        if up.returncode != 0:
            pytest.skip(f"docker compose up failed: {up.stderr.strip()}")

    try:
        endpoints = _required_endpoints()
        pg_host, pg_port = endpoints["postgres"]
        ch_host, ch_port = endpoints["clickhouse"]
        qdrant_host, qdrant_port = endpoints["qdrant"]

        if not _wait_for_postgres_ready(host=pg_host, port=pg_port):
            pytest.skip("postgres did not become ready in time")
        if not _wait_for_clickhouse_ready():
            pytest.skip("clickhouse did not become ready in time")
        if not _wait_for_qdrant_ready(host=qdrant_host, port=qdrant_port):
            pytest.skip("qdrant did not become ready in time")

        _ensure_delivery_tables(postgres_host=pg_host, postgres_port=pg_port)
        _seed_clickhouse_feature_slice()
        _configure_live_runtime(
            monkeypatch=monkeypatch,
            postgres_host=pg_host,
            postgres_port=pg_port,
            clickhouse_host=ch_host,
            clickhouse_port=ch_port,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
        )

        summary = run_flow.run_minimal_vertical_slice(
            campaign_id="camp_admin_delivery_api_e2e",
            policy_version="policy_credit_v1",
            integration_profile_id="clickhouse_postgres_export",
            delivery_target_id="crm_postgres_outbox",
            requested_size=3,
        )
        run_id = summary["versions"]["run_id"]
        initial_job_id = summary["delivery"]["delivery_job_id"]
        assert summary["delivery"]["status"] == "delivered"

        monkeypatch.setenv("AE_ADMIN_API_KEYS", "admin_live_key")
        monkeypatch.setenv("AE_CAMPAIGN_API_KEYS", "campaign_live_key")
        client = TestClient(retrieval_api_app.app)
        headers = {"X-AE-API-Key": "admin_live_key"}

        targets_resp = client.get(
            "/v1/admin/control-plane/delivery-targets?include_planned=false",
            headers=headers,
        )
        jobs_resp = client.get("/v1/admin/delivery/jobs/recent?limit=50", headers=headers)
        attempts_resp = client.get(
            f"/v1/admin/delivery/attempts/recent?run_id={run_id}&limit=50",
            headers=headers,
        )
        summary_resp = client.get(
            f"/v1/admin/delivery/runs/{run_id}/latest-summary",
            headers=headers,
        )
        records_resp = client.get(
            f"/v1/admin/delivery/runs/{run_id}/records?limit=200",
            headers=headers,
        )

        assert targets_resp.status_code == 200
        assert jobs_resp.status_code == 200
        assert attempts_resp.status_code == 200
        assert summary_resp.status_code == 200
        assert records_resp.status_code == 200
        assert any(
            row["delivery_job_id"] == initial_job_id for row in jobs_resp.json()["jobs"]
        )
        assert summary_resp.json()["delivery_job_id"] == initial_job_id
        assert records_resp.json()["count"] >= 1

        retry_resp = client.post(
            "/v1/admin/delivery/trigger",
            json={"run_id": run_id, "delivery_target_id": "crm_postgres_outbox"},
            headers=headers,
        )
        assert retry_resp.status_code == 200
        assert retry_resp.json()["status"] == "skipped_conflict"

        jobs_after_retry = client.get(
            "/v1/admin/delivery/jobs/recent?limit=50",
            headers=headers,
        )
        assert jobs_after_retry.status_code == 200
        jobs_for_run = [
            row for row in jobs_after_retry.json()["jobs"] if row.get("run_id") == run_id
        ]
        assert len(jobs_for_run) >= 2
        assert jobs_for_run[0]["status"] in {"skipped_conflict", "delivered"}
    finally:
        if started_by_test and not _prefer_stack_preservation():
            _compose("stop", *sorted(started_by_test))
