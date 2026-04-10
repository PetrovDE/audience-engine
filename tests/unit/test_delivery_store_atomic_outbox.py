from __future__ import annotations

from datetime import datetime, timezone

from pipelines.minimal_slice import delivery_store
from pipelines.minimal_slice.delivery_contract import StagedAudienceRow


def _row() -> StagedAudienceRow:
    return StagedAudienceRow(
        run_id="7bf0c5be-f95c-4827-a5c4-6ee71f2807f2",
        campaign_id="camp_delivery",
        customer_id="cust_001",
        status="approve",
        final_score=0.91,
        rank=1,
        channel="email",
        policy_version="policy_credit_v1",
        fs_version="fs_credit_v1",
        emb_version="fs_credit_v1+prompt_credit_v1+nomic-embed-text",
        model_version="nomic-embed-text",
        index_alias="audience-serving",
        index_generation="audience-serving-fs_credit_v1-abc12345",
        integration_profile_id="clickhouse_postgres_export",
        source_id="clickhouse_feature_slice",
        export_target_id="postgres_export_table",
        exported_ts=datetime(2026, 4, 9, 15, 0, tzinfo=timezone.utc),
        export_context={"reason_codes": ["NONE"]},
    )


def test_atomic_outbox_delivery_persists_outbox_and_records_in_single_commit(monkeypatch):
    executed: list[str] = []
    commits = {"count": 0}

    class _Cursor:
        def __init__(self):
            self.rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            q = str(query)
            executed.append(q)
            if "INSERT INTO audience_crm_postgres_outbox" in q:
                self.rowcount = 1
            elif "INSERT INTO audience_delivery_record" in q:
                self.rowcount = 1
            else:
                self.rowcount = 0

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return _Cursor()

        def commit(self):
            commits["count"] += 1

    class _Psycopg:
        @staticmethod
        def connect(conninfo):
            return _Connection()

    monkeypatch.setattr(delivery_store, "_psycopg", lambda: (_Psycopg(), object()))
    monkeypatch.setattr(delivery_store, "POSTGRES_HOST", "localhost")
    monkeypatch.setattr(delivery_store, "POSTGRES_PORT", 5432)
    monkeypatch.setattr(delivery_store, "POSTGRES_DB", "audience_engine")
    monkeypatch.setattr(delivery_store, "POSTGRES_USER", "audience_engine")
    monkeypatch.setattr(delivery_store, "POSTGRES_PASSWORD", "secret")
    monkeypatch.setattr(delivery_store, "POSTGRES_SSLMODE", "")

    result = delivery_store.execute_crm_postgres_outbox_delivery_atomic(
        run_id="7bf0c5be-f95c-4827-a5c4-6ee71f2807f2",
        campaign_id="camp_delivery",
        delivery_target_id="crm_postgres_outbox",
        trigger_source="api:/test",
        requested_by_role="admin_operator",
        requested_by_id="admin:test",
        staged_rows=[_row()],
    )

    assert result["status"] == "delivered"
    assert result["rows_delivered"] == 1
    assert commits["count"] == 1
    assert any("INSERT INTO audience_crm_postgres_outbox" in q for q in executed)
    assert any("INSERT INTO audience_delivery_record" in q for q in executed)


def test_atomic_outbox_delivery_reports_no_source_rows_status(monkeypatch):
    class _Cursor:
        def __init__(self):
            self.rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            self.rowcount = 0

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return _Cursor()

        def commit(self):
            return None

    class _Psycopg:
        @staticmethod
        def connect(conninfo):
            return _Connection()

    monkeypatch.setattr(delivery_store, "_psycopg", lambda: (_Psycopg(), object()))
    monkeypatch.setattr(delivery_store, "POSTGRES_HOST", "localhost")
    monkeypatch.setattr(delivery_store, "POSTGRES_PORT", 5432)
    monkeypatch.setattr(delivery_store, "POSTGRES_DB", "audience_engine")
    monkeypatch.setattr(delivery_store, "POSTGRES_USER", "audience_engine")
    monkeypatch.setattr(delivery_store, "POSTGRES_PASSWORD", "secret")
    monkeypatch.setattr(delivery_store, "POSTGRES_SSLMODE", "")

    result = delivery_store.execute_crm_postgres_outbox_delivery_atomic(
        run_id="7bf0c5be-f95c-4827-a5c4-6ee71f2807f2",
        campaign_id="camp_delivery",
        delivery_target_id="crm_postgres_outbox",
        trigger_source="api:/test",
        requested_by_role="admin_operator",
        requested_by_id="admin:test",
        staged_rows=[],
    )

    assert result["status"] == "skipped_no_source_rows"
    assert result["rows_delivered"] == 0
