from __future__ import annotations

from pipelines.minimal_slice import export_table


def test_write_approved_to_postgres_export_table_writes_contract_rows(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def executemany(self, query, rows):
            captured["query"] = query
            captured["rows"] = list(rows)

    class _FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return _FakeCursor()

        def commit(self):
            captured["committed"] = True

    class _FakePsycopg:
        @staticmethod
        def connect(conninfo):
            captured["conninfo"] = conninfo
            return _FakeConnection()

    monkeypatch.setattr(export_table, "_psycopg", lambda: _FakePsycopg())
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_HOST", "localhost")
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_PORT", 5432)
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_DB", "audience_engine")
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_USER", "audience_engine")
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_PASSWORD", "secret")
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_SCHEMA", "public")
    monkeypatch.setattr(
        export_table, "EXPORT_POSTGRES_TABLE", "audience_export_staging"
    )
    monkeypatch.setattr(export_table, "EXPORT_POSTGRES_SSLMODE", "")

    policy_result = {
        "results": [
            {
                "customer_id": "cust_001",
                "decision": "approve",
                "score": 0.99,
                "reasons": [],
            },
            {
                "customer_id": "cust_002",
                "decision": "reject",
                "score": 0.8,
                "reasons": [{"reason_code": "SUPPRESS_DNC"}],
            },
            {
                "customer_id": "cust_003",
                "decision": "approve",
                "score": 0.7,
                "reasons": [{"reason_code": "ELIGIBILITY_TENURE_LT_3M"}],
            },
        ]
    }
    export_context = {
        "run_id": "7bf0c5be-f95c-4827-a5c4-6ee71f2807f2",
        "campaign_id": "camp_export",
        "policy_version": "policy_credit_v1",
        "fs_version": "fs_credit_v1",
        "emb_version": "fs_credit_v1+prompt_credit_v1+nomic-embed-text",
        "model_version": "nomic-embed-text",
        "index_alias": "audience-serving",
        "index_generation": "customers_fs_credit_v1_8d_20260409000000",
        "integration_profile_id": "clickhouse_postgres_export",
        "source_id": "clickhouse_feature_slice",
        "export_id": "postgres_export_table",
        "channel": "email",
        "exported_ts": "2026-04-09T12:34:56+00:00",
    }

    meta = export_table.write_approved_to_postgres_export_table(
        policy_result=policy_result,
        export_context=export_context,
    )

    assert meta["rows_written"] == 2
    assert meta["table"] == "public.audience_export_staging"
    assert meta["status"] == "written"
    assert "INSERT INTO public.audience_export_staging" in str(captured["query"])
    assert len(captured["rows"]) == 2
    assert captured["rows"][0][2] == "cust_001"
    assert captured["rows"][1][2] == "cust_003"
    assert captured["committed"] is True


def test_write_approved_to_postgres_export_table_requires_run_id():
    try:
        export_table.write_approved_to_postgres_export_table(
            policy_result={"results": []},
            export_context={
                "campaign_id": "camp_export",
                "policy_version": "policy_credit_v1",
                "fs_version": "fs_credit_v1",
                "emb_version": "fs_credit_v1+prompt_credit_v1+nomic-embed-text",
                "model_version": "nomic-embed-text",
                "index_alias": "audience-serving",
                "index_generation": "customers_fs_credit_v1_8d_20260409000000",
                "integration_profile_id": "clickhouse_postgres_export",
                "source_id": "clickhouse_feature_slice",
                "export_id": "postgres_export_table",
            },
        )
    except ValueError as exc:
        assert "export_context fields: run_id" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError for missing run_id")
