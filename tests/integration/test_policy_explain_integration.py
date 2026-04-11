from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

from pipelines.minimal_slice import config
from pipelines.minimal_slice.policy_decision_audit import (
    build_policy_decision_audit_rows,
    write_policy_decision_audit_rows,
)
from pipelines.version_bundle import VersionBundle
from services.retrieval_api import app as app_module

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


def _postgres_conninfo() -> str:
    return (
        f"host={config.POSTGRES_HOST} "
        f"port={config.POSTGRES_PORT} "
        f"dbname={config.POSTGRES_DB} "
        f"user={config.POSTGRES_USER} "
        f"password={config.POSTGRES_PASSWORD}"
    )


def _wait_for_postgres_ready(timeout_seconds: float = 30.0) -> None:
    if psycopg is None:
        return
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(_postgres_conninfo()) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            return
        except Exception as exc:  # pragma: no cover - environment-dependent
            last_error = exc
            time.sleep(0.5)
    pytest.fail(
        "postgres container did not become ready within timeout after compose up; "
        f"last_error={last_error}"
    )


def test_policy_explain_reads_real_db_backed_decision():
    if psycopg is None:
        pytest.skip("psycopg is not installed")
    if not _docker_available():
        pytest.skip("docker is not available")
    _ensure_env_file()

    up = _compose("up", "-d", "postgres")
    if up.returncode != 0:
        pytest.skip(f"docker compose up failed: {up.stderr.strip()}")
    _wait_for_postgres_ready(timeout_seconds=45.0)
    try:
        run_id = str(uuid4())
        bundle = VersionBundle(
            fs_version="fs_credit_v1",
            emb_version="fs_credit_v1+prompt_credit_v1+nomic-embed-text",
            model_version="nomic-embed-text",
            policy_version=config.POLICY_VERSION,
            index_alias=config.QDRANT_ALIAS,
            concrete_qdrant_collection="customers_fs_credit_v1_8d_20260408123456",
            run_id=run_id,
            campaign_id="camp_explain_real",
        )
        policy_result = {
            "results": [
                {
                    "customer_id": "cust_explain_001",
                    "decision": "reject",
                    "score": 0.11,
                    "selected": False,
                    "reasons": [
                        {
                            "reason_code": "POLICY_FAIL_CLOSED_REQUIRED_INPUT",
                            "reason_class": "system",
                            "message": "required input failure",
                            "rule_id": "system.fail_closed.required_input",
                            "priority": 0,
                        }
                    ],
                    "explanation": {
                        "evaluation_mode": "fail_closed_required_inputs",
                        "details": {"source": "integration_test"},
                    },
                }
            ]
        }
        decision_rows = build_policy_decision_audit_rows(
            policy_result=policy_result,
            bundle=bundle,
            resolved_collection=bundle.concrete_qdrant_collection,
            decision_ts="2026-04-08T12:34:56+00:00",
        )

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
                    )
                    VALUES (%s, %s, %s, now(), %s::jsonb, %s::jsonb)
                    """,
                    (
                        run_id,
                        bundle.campaign_id,
                        "integration_policy_explain",
                        json.dumps(
                            {
                                "fs_version": bundle.fs_version,
                                "emb_version": bundle.emb_version,
                                "model_version": bundle.model_version,
                                "policy_version": bundle.policy_version,
                                "index_alias": bundle.index_alias,
                                "concrete_qdrant_collection": (
                                    bundle.concrete_qdrant_collection
                                ),
                                "run_id": bundle.run_id,
                                "campaign_id": bundle.campaign_id,
                            }
                        ),
                        json.dumps({"integration": "policy_explain"}),
                    ),
                )
                write_policy_decision_audit_rows(cur, decision_rows)
            conn.commit()

        client = TestClient(app_module.app)
        os.environ["AE_CAMPAIGN_API_KEYS"] = "campaign-test-key"
        os.environ["AE_ADMIN_API_KEYS"] = "admin-test-key"
        response = client.get(
            f"/v1/policy/decisions/{run_id}/cust_explain_001",
            headers={"X-AE-API-Key": "admin-test-key"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["run_id"] == run_id
        assert payload["customer_id"] == "cust_explain_001"
        assert payload["decision"] == "reject"
        assert payload["reason_codes"] == ["POLICY_FAIL_CLOSED_REQUIRED_INPUT"]
        assert payload["policy_version"] == config.POLICY_VERSION
        assert (
            payload["emb_version"] == "fs_credit_v1+prompt_credit_v1+nomic-embed-text"
        )
    finally:
        _compose("down")
