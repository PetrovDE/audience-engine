from __future__ import annotations

from datetime import datetime, timezone

from pipelines.minimal_slice import delivery_store
from pipelines.minimal_slice.delivery_contract import StagedAudienceRow


def _staged_rows() -> list[StagedAudienceRow]:
    exported_ts = datetime(2026, 4, 9, 15, 0, tzinfo=timezone.utc)
    base = {
        "run_id": "7bf0c5be-f95c-4827-a5c4-6ee71f2807f2",
        "campaign_id": "camp_delivery",
        "status": "approve",
        "channel": "email",
        "policy_version": "policy_credit_v1",
        "fs_version": "fs_credit_v1",
        "emb_version": "fs_credit_v1+prompt_credit_v1+nomic-embed-text",
        "model_version": "nomic-embed-text",
        "index_alias": "audience-serving",
        "index_generation": "audience-serving-fs_credit_v1-abc12345",
        "integration_profile_id": "clickhouse_postgres_export",
        "source_id": "clickhouse_feature_slice",
        "export_target_id": "postgres_export_table",
        "exported_ts": exported_ts,
        "export_context": {"reason_codes": []},
    }
    return [
        StagedAudienceRow(customer_id="cust_001", final_score=0.9, rank=1, **base),
        StagedAudienceRow(customer_id="cust_002", final_score=0.8, rank=2, **base),
    ]


def test_write_crm_postgres_outbox_is_idempotent(monkeypatch):
    seen_keys: set[tuple[str, str, str]] = set()

    class _FakeCursor:
        def __init__(self):
            self.rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            key = (str(params[0]), str(params[2]), str(params[3]))
            if key in seen_keys:
                self.rowcount = 0
            else:
                seen_keys.add(key)
                self.rowcount = 1

    class _FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return _FakeCursor()

        def commit(self):
            return None

    class _FakePsycopg:
        @staticmethod
        def connect(conninfo):
            return _FakeConnection()

    monkeypatch.setattr(delivery_store, "_psycopg", lambda: (_FakePsycopg(), object()))
    monkeypatch.setattr(delivery_store, "POSTGRES_HOST", "localhost")
    monkeypatch.setattr(delivery_store, "POSTGRES_PORT", 5432)
    monkeypatch.setattr(delivery_store, "POSTGRES_DB", "audience_engine")
    monkeypatch.setattr(delivery_store, "POSTGRES_USER", "audience_engine")
    monkeypatch.setattr(delivery_store, "POSTGRES_PASSWORD", "secret")
    monkeypatch.setattr(delivery_store, "POSTGRES_SSLMODE", "")

    rows = _staged_rows()
    first = delivery_store.write_crm_postgres_outbox(
        rows=rows,
        delivery_target_id="crm_postgres_outbox",
        delivery_job_id="f4cfa9e8-6a57-4a54-aef4-f0398102f2fb",
    )
    second = delivery_store.write_crm_postgres_outbox(
        rows=rows,
        delivery_target_id="crm_postgres_outbox",
        delivery_job_id="f4cfa9e8-6a57-4a54-aef4-f0398102f2fb",
    )

    assert first["rows_attempted"] == 2
    assert first["rows_written"] == 2
    assert first["rows_skipped_conflict"] == 0
    assert second["rows_attempted"] == 2
    assert second["rows_written"] == 0
    assert second["rows_skipped_conflict"] == 2
