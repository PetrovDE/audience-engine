from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest

try:
    import psycopg
    from psycopg.errors import ForeignKeyViolation
except ImportError:  # pragma: no cover
    psycopg = None
    ForeignKeyViolation = Exception

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "infra" / "docker-compose.dev.yml"
ENV_FILE = ROOT / "infra" / ".env"
ENV_EXAMPLE_FILE = ROOT / "infra" / ".env.example"
REGISTRY_MIGRATION_SQL = (
    ROOT / "infra" / "postgres" / "migrations" / "008_control_plane_registry_v1.sql"
)


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


def _parse_endpoint(raw: str) -> tuple[str, int]:
    value = raw.strip()
    if ":" not in value:
        raise ValueError(f"Could not parse docker compose port output: {raw!r}")
    host, port_s = value.rsplit(":", 1)
    return host, int(port_s)


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
    host, port = _parse_endpoint(lines[0])
    if host in {"0.0.0.0", "::", "[::]", ""}:
        host = "127.0.0.1"
    if host == "localhost":
        host = "127.0.0.1"
    return host, port


def _wait_for_postgres_ready(
    host: str, port: int, timeout_seconds: float = 45.0
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


def _postgres_conninfo(*, host: str, port: int) -> str:
    return (
        f"host={host} "
        f"port={port} "
        "dbname=audience_engine "
        "user=audience_engine "
        "password=change_me"
    )


def test_control_plane_registry_db_referential_integrity_and_lineage():
    if psycopg is None:
        pytest.skip("psycopg is not installed")
    if not _docker_available():
        pytest.skip("docker is not available")

    _ensure_env_file()
    started_postgres = False
    running_before = _running_services()
    if "postgres" not in running_before:
        up = _compose("up", "-d", "postgres")
        if up.returncode != 0:
            pytest.skip(f"docker compose up postgres failed: {up.stderr.strip()}")
        started_postgres = True

    try:
        pg_host, pg_port = _compose_endpoint("postgres", 5432)
        if not _wait_for_postgres_ready(pg_host, pg_port):
            pytest.skip("postgres did not become ready in time")

        conninfo = _postgres_conninfo(host=pg_host, port=pg_port)
        with psycopg.connect(conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute(REGISTRY_MIGRATION_SQL.read_text(encoding="utf-8"))

                feature_set_id = str(uuid4())
                feature_set_version_id = str(uuid4())
                model_id = str(uuid4())
                model_version_id = str(uuid4())
                provider_id = str(uuid4())
                embedding_model_version_id = str(uuid4())
                policy_id = str(uuid4())
                policy_version_id = str(uuid4())
                audience_definition_id = str(uuid4())
                audience_definition_version_id = str(uuid4())
                run_id = str(uuid4())

                cur.execute(
                    """
                    INSERT INTO feature_sets (id, feature_set_key, metadata)
                    VALUES (%s::uuid, %s, '{}'::jsonb)
                    """,
                    (feature_set_id, f"fs_test_{uuid4().hex[:8]}"),
                )
                cur.execute(
                    """
                    INSERT INTO feature_set_versions (
                        id, feature_set_id, version, lifecycle_state, payload
                    )
                    VALUES (%s::uuid, %s::uuid, %s, 'active', '{}'::jsonb)
                    """,
                    (feature_set_version_id, feature_set_id, "fs_test_v1"),
                )

                cur.execute(
                    """
                    INSERT INTO models (id, model_key, metadata)
                    VALUES (%s::uuid, %s, '{}'::jsonb)
                    """,
                    (model_id, f"model_test_{uuid4().hex[:8]}"),
                )
                cur.execute(
                    """
                    INSERT INTO model_versions (
                        id, model_id, version, lifecycle_state, payload
                    )
                    VALUES (%s::uuid, %s::uuid, %s, 'active', '{}'::jsonb)
                    """,
                    (model_version_id, model_id, "model_test_v1"),
                )

                cur.execute(
                    """
                    INSERT INTO embedding_providers (id, provider_key, metadata)
                    VALUES (%s::uuid, %s, '{}'::jsonb)
                    """,
                    (provider_id, f"provider_test_{uuid4().hex[:8]}"),
                )
                cur.execute(
                    """
                    INSERT INTO embedding_model_versions (
                        id,
                        embedding_provider_id,
                        model_version_id,
                        version,
                        provider_model_ref,
                        capability,
                        lifecycle_state,
                        payload
                    )
                    VALUES (
                        %s::uuid,
                        %s::uuid,
                        %s::uuid,
                        %s,
                        %s,
                        'embedding',
                        'active',
                        '{}'::jsonb
                    )
                    """,
                    (
                        embedding_model_version_id,
                        provider_id,
                        model_version_id,
                        "embedding_test_v1",
                        "local:test-model",
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO policies (id, policy_key, metadata)
                    VALUES (%s::uuid, %s, '{}'::jsonb)
                    """,
                    (policy_id, f"policy_test_{uuid4().hex[:8]}"),
                )
                cur.execute(
                    """
                    INSERT INTO policy_versions (
                        id, policy_id, version, lifecycle_state, payload
                    )
                    VALUES (%s::uuid, %s::uuid, %s, 'active', '{}'::jsonb)
                    """,
                    (policy_version_id, policy_id, "policy_test_v1"),
                )

                cur.execute(
                    """
                    INSERT INTO audience_definitions (
                        id, audience_definition_key, metadata
                    )
                    VALUES (%s::uuid, %s, '{}'::jsonb)
                    """,
                    (audience_definition_id, f"aud_def_test_{uuid4().hex[:8]}"),
                )
                cur.execute(
                    """
                    INSERT INTO audience_definition_versions (
                        id,
                        audience_definition_id,
                        feature_set_version_id,
                        policy_version_id,
                        version,
                        lifecycle_state,
                        payload
                    )
                    VALUES (
                        %s::uuid,
                        %s::uuid,
                        %s::uuid,
                        %s::uuid,
                        %s,
                        'active',
                        '{}'::jsonb
                    )
                    """,
                    (
                        audience_definition_version_id,
                        audience_definition_id,
                        feature_set_version_id,
                        policy_version_id,
                        "aud_def_test_v1",
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO audience_run (
                        run_id,
                        campaign_id,
                        product_id,
                        run_ts,
                        version_bundle,
                        parameters
                    )
                    VALUES (
                        %s::uuid,
                        %s,
                        %s,
                        NOW(),
                        '{}'::jsonb,
                        '{}'::jsonb
                    )
                    """,
                    (run_id, "camp_registry_test", "registry_test"),
                )
                cur.execute(
                    """
                    INSERT INTO audience_run_lineage_binding (
                        run_id,
                        feature_set_version_id,
                        model_version_id,
                        embedding_model_version_id,
                        policy_version_id,
                        audience_definition_version_id,
                        delivery_target_id,
                        export_profile_id
                    )
                    VALUES (
                        %s::uuid,
                        %s::uuid,
                        %s::uuid,
                        %s::uuid,
                        %s::uuid,
                        %s::uuid,
                        %s,
                        %s
                    )
                    """,
                    (
                        run_id,
                        feature_set_version_id,
                        model_version_id,
                        embedding_model_version_id,
                        policy_version_id,
                        audience_definition_version_id,
                        "crm_csv_file",
                        "clickhouse_postgres_export",
                    ),
                )
                cur.execute(
                    """
                    SELECT
                        feature_set_version_id::text,
                        model_version_id::text,
                        embedding_model_version_id::text,
                        policy_version_id::text,
                        audience_definition_version_id::text
                    FROM audience_run_lineage_binding
                    WHERE run_id = %s::uuid
                    """,
                    (run_id,),
                )
                row = cur.fetchone()
            conn.commit()

            assert row is not None
            assert row[0] == feature_set_version_id
            assert row[1] == model_version_id
            assert row[2] == embedding_model_version_id
            assert row[3] == policy_version_id
            assert row[4] == audience_definition_version_id

            invalid_run_id = str(uuid4())
            try:
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
                        )
                        VALUES (
                            %s::uuid,
                            %s,
                            %s,
                            NOW(),
                            '{}'::jsonb,
                            '{}'::jsonb
                        )
                        """,
                        (invalid_run_id, "camp_registry_test_bad", "registry_test"),
                    )
                    with pytest.raises(ForeignKeyViolation):
                        cur.execute(
                            """
                            INSERT INTO audience_run_lineage_binding (
                                run_id,
                                feature_set_version_id
                            )
                            VALUES (%s::uuid, %s::uuid)
                            """,
                            (invalid_run_id, str(uuid4())),
                        )
            finally:
                conn.rollback()
    finally:
        if started_postgres and not _prefer_stack_preservation():
            _compose("down")
