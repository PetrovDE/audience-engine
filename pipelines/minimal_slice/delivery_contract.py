from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

DELIVERY_STATUSES: tuple[str, ...] = (
    "pending",
    "materialized",
    "delivered",
    "failed",
    "skipped_conflict",
)

CRM_CSV_COLUMNS: tuple[str, ...] = (
    "run_id",
    "campaign_id",
    "customer_id",
    "policy_version",
    "integration_profile_id",
    "source_id",
    "export_target_id",
    "delivery_target_id",
    "delivery_job_id",
    "delivery_status",
    "final_score",
    "rank",
    "channel",
    "fs_version",
    "emb_version",
    "model_version",
    "index_alias",
    "index_generation",
    "exported_ts",
    "delivered_ts",
)


@dataclass(frozen=True)
class StagedAudienceRow:
    run_id: str
    campaign_id: str
    customer_id: str
    status: str
    final_score: float
    rank: int
    channel: str
    policy_version: str
    fs_version: str
    emb_version: str
    model_version: str
    index_alias: str
    index_generation: str
    integration_profile_id: str
    source_id: str
    export_target_id: str
    exported_ts: datetime
    export_context: dict[str, Any]

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "StagedAudienceRow":
        exported_ts = row["exported_ts"]
        if not isinstance(exported_ts, datetime):
            raise ValueError("audience_export_staging.exported_ts must be datetime")
        export_context = row.get("export_context")
        if not isinstance(export_context, dict):
            export_context = {}
        return cls(
            run_id=str(row["run_id"]),
            campaign_id=str(row["campaign_id"]),
            customer_id=str(row["customer_id"]),
            status=str(row["status"]),
            final_score=float(row["final_score"]),
            rank=int(row["rank"]),
            channel=str(row["channel"]),
            policy_version=str(row["policy_version"]),
            fs_version=str(row["fs_version"]),
            emb_version=str(row["emb_version"]),
            model_version=str(row["model_version"]),
            index_alias=str(row["index_alias"]),
            index_generation=str(row["index_generation"]),
            integration_profile_id=str(row["integration_profile_id"]),
            source_id=str(row["source_id"]),
            export_target_id=str(row["export_target_id"]),
            exported_ts=exported_ts,
            export_context=export_context,
        )

    def to_crm_csv_row(
        self,
        *,
        delivery_target_id: str,
        delivery_job_id: str,
        delivery_status: str,
        delivered_ts: datetime,
    ) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "campaign_id": self.campaign_id,
            "customer_id": self.customer_id,
            "policy_version": self.policy_version,
            "integration_profile_id": self.integration_profile_id,
            "source_id": self.source_id,
            "export_target_id": self.export_target_id,
            "delivery_target_id": delivery_target_id,
            "delivery_job_id": delivery_job_id,
            "delivery_status": delivery_status,
            "final_score": f"{self.final_score:.10f}",
            "rank": self.rank,
            "channel": self.channel,
            "fs_version": self.fs_version,
            "emb_version": self.emb_version,
            "model_version": self.model_version,
            "index_alias": self.index_alias,
            "index_generation": self.index_generation,
            "exported_ts": self.exported_ts.isoformat(),
            "delivered_ts": delivered_ts.isoformat(),
        }


def sort_staged_rows(rows: list[StagedAudienceRow]) -> list[StagedAudienceRow]:
    return sorted(rows, key=lambda row: (row.rank, row.customer_id))


def ensure_delivery_status(status: str) -> str:
    if status not in DELIVERY_STATUSES:
        raise ValueError(f"Unsupported delivery status: {status}")
    return status
