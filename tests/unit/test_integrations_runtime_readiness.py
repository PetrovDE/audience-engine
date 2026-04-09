from __future__ import annotations

from pathlib import Path

from pipelines.minimal_slice import integrations


def test_annotate_runtime_readiness_marks_clickhouse_postgres_profile_runnable():
    result = integrations.annotate_runtime_readiness(
        sources=[
            {
                "source_id": "clickhouse_feature_slice",
                "implementation_status": "implemented",
            }
        ],
        exports=[
            {
                "export_id": "postgres_export_table",
                "implementation_status": "implemented",
            }
        ],
        profiles=[
            {
                "profile_id": "clickhouse_postgres_export",
                "implementation_status": "implemented",
                "source_id": "clickhouse_feature_slice",
                "export_id": "postgres_export_table",
            }
        ],
    )

    assert result["sources"][0]["runtime_runnable"] is True
    assert result["exports"][0]["runtime_runnable"] is True
    assert result["profiles"][0]["runtime_runnable"] is True
    assert result["profiles"][0]["runtime_validation_errors"] == []


def test_export_for_profile_passes_export_context_to_target(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class _FakeSource:
        connector_id = "clickhouse_feature_slice"

        def validate_config(self):
            return None

        def build_feature_mart(self, *, raw_path, output_path, run_id):
            return output_path

    class _FakeTarget:
        target_id = "postgres_export_table"

        def validate_config(self):
            return None

        def export(
            self,
            *,
            policy_result,
            output_path,
            run_id,
            export_context=None,
        ):
            captured["export_context"] = export_context
            return {
                "target_id": self.target_id,
                "export_path": str(output_path),
                "export_uri": None,
                "status": "written_and_persisted",
            }

    monkeypatch.setattr(
        integrations,
        "get_integration_profile",
        lambda profile_id: {
            "profile_id": "clickhouse_postgres_export",
            "implementation_status": "implemented",
            "source_id": "clickhouse_feature_slice",
            "export_id": "postgres_export_table",
        },
    )
    monkeypatch.setitem(
        integrations._SOURCE_CONNECTORS,  # type: ignore[attr-defined]
        "clickhouse_feature_slice",
        _FakeSource(),
    )
    monkeypatch.setitem(
        integrations._EXPORT_TARGETS,  # type: ignore[attr-defined]
        "postgres_export_table",
        _FakeTarget(),
    )

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

    result = integrations.export_for_profile(
        profile_id="clickhouse_postgres_export",
        policy_result={"results": []},
        run_id="7bf0c5be-f95c-4827-a5c4-6ee71f2807f2",
        output_path=Path(tmp_path / "approved_audience.jsonl"),
        export_context=export_context,
    )

    assert result["export_id"] == "postgres_export_table"
    assert captured["export_context"] == export_context
