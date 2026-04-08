from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import GOVERNANCE_DIR

RAW_CONTRACT_PATH = GOVERNANCE_DIR / "contracts" / "raw.yaml"
FEATURE_MART_CONTRACT_PATH = GOVERNANCE_DIR / "contracts" / "feature_mart.yaml"


@dataclass(frozen=True)
class DataQualityError(RuntimeError):
    code: str
    dataset: str
    path: str
    detail: str
    line_number: int | None = None
    field: str | None = None

    def __str__(self) -> str:
        parts = [f"code={self.code}", f"dataset={self.dataset}", f"path={self.path}"]
        if self.line_number is not None:
            parts.append(f"line={self.line_number}")
        if self.field:
            parts.append(f"field={self.field}")
        parts.append(f"detail={self.detail}")
        return "DataQualityError(" + ", ".join(parts) + ")"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "dataset": self.dataset,
            "path": self.path,
            "detail": self.detail,
            "line_number": self.line_number,
            "field": self.field,
        }


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _raise(
    *,
    code: str,
    dataset: str,
    path: Path,
    detail: str,
    line_number: int | None = None,
    field: str | None = None,
) -> None:
    raise DataQualityError(
        code=code,
        dataset=dataset,
        path=str(path),
        detail=detail,
        line_number=line_number,
        field=field,
    )


def _load_contract(contract_path: Path) -> dict[str, Any]:
    if not contract_path.exists():
        _raise(
            code="DQ_CONTRACT_MISSING",
            dataset="contract",
            path=contract_path,
            detail="contract file does not exist",
        )
    with contract_path.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    if not isinstance(payload, dict):
        _raise(
            code="DQ_CONTRACT_INVALID",
            dataset="contract",
            path=contract_path,
            detail="contract file must contain a YAML object",
        )
    return payload


def _iter_jsonl_rows(path: Path, dataset: str) -> list[tuple[int, dict[str, Any]]]:
    if not path.exists():
        _raise(
            code="DQ_SOURCE_MISSING",
            dataset=dataset,
            path=path,
            detail="input file does not exist",
        )
    rows: list[tuple[int, dict[str, Any]]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError as exc:
                    _raise(
                        code="DQ_INVALID_JSON",
                        dataset=dataset,
                        path=path,
                        detail=f"invalid JSON row: {exc}",
                        line_number=line_number,
                    )
                if not isinstance(row, dict):
                    _raise(
                        code="DQ_INVALID_ROW",
                        dataset=dataset,
                        path=path,
                        detail="row must be a JSON object",
                        line_number=line_number,
                    )
                rows.append((line_number, row))
    except OSError as exc:
        _raise(
            code="DQ_SOURCE_UNREADABLE",
            dataset=dataset,
            path=path,
            detail=f"input file could not be read: {exc}",
        )

    if not rows:
        _raise(
            code="DQ_EMPTY_DATASET",
            dataset=dataset,
            path=path,
            detail="dataset has no records",
        )
    return rows


def _is_type_valid(expected_type: str, value: Any) -> bool:
    etype = expected_type.lower()
    if etype in {"string", "str"}:
        return isinstance(value, str)
    if etype in {"int", "integer"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if etype in {"float", "decimal", "number"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if etype in {"bool", "boolean"}:
        return isinstance(value, bool)
    if etype in {"timestamp", "datetime"}:
        return isinstance(value, str) and _parse_ts(value) is not None
    return True


def validate_jsonl_against_contract(
    *,
    dataset_name: str,
    data_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    contract = _load_contract(contract_path)
    rows = _iter_jsonl_rows(data_path, dataset_name)
    fields = contract.get("fields", [])
    required_versions = contract.get("required_versions", [])
    primary_key = contract.get("primary_key", [])

    required_fields = [f for f in fields if f.get("required", False)]
    seen_primary_keys: set[tuple[Any, ...]] = set()
    for line_number, row in rows:
        for field_def in required_fields:
            field_name = str(field_def["name"])
            if row.get(field_name) in (None, ""):
                _raise(
                    code="DQ_REQUIRED_FIELD_MISSING",
                    dataset=dataset_name,
                    path=data_path,
                    detail="required field missing or empty",
                    line_number=line_number,
                    field=field_name,
                )
            expected_type = str(field_def.get("type", ""))
            if expected_type and not _is_type_valid(expected_type, row[field_name]):
                _raise(
                    code="DQ_TYPE_MISMATCH",
                    dataset=dataset_name,
                    path=data_path,
                    detail=f"expected type {expected_type}",
                    line_number=line_number,
                    field=field_name,
                )

        for field_name in required_versions:
            if row.get(field_name) in (None, ""):
                _raise(
                    code="DQ_REQUIRED_VERSION_MISSING",
                    dataset=dataset_name,
                    path=data_path,
                    detail="required version field missing or empty",
                    line_number=line_number,
                    field=str(field_name),
                )

        if primary_key:
            key = tuple(row.get(pk) for pk in primary_key)
            if any(v in (None, "") for v in key):
                _raise(
                    code="DQ_PRIMARY_KEY_MISSING",
                    dataset=dataset_name,
                    path=data_path,
                    detail="primary key value missing",
                    line_number=line_number,
                )
            if key in seen_primary_keys:
                _raise(
                    code="DQ_PRIMARY_KEY_DUPLICATE",
                    dataset=dataset_name,
                    path=data_path,
                    detail=f"duplicate primary key detected: {key}",
                    line_number=line_number,
                )
            seen_primary_keys.add(key)

    return {
        "status": "passed",
        "dataset": dataset_name,
        "path": str(data_path),
        "contract": str(contract_path),
        "record_count": len(rows),
        "required_fields_checked": [str(f["name"]) for f in required_fields],
        "required_versions_checked": [str(v) for v in required_versions],
    }


def validate_raw_contract(raw_path: Path) -> dict[str, Any]:
    return validate_jsonl_against_contract(
        dataset_name="raw",
        data_path=raw_path,
        contract_path=RAW_CONTRACT_PATH,
    )


def validate_feature_mart_contract(feature_mart_path: Path) -> dict[str, Any]:
    return validate_jsonl_against_contract(
        dataset_name="feature_mart",
        data_path=feature_mart_path,
        contract_path=FEATURE_MART_CONTRACT_PATH,
    )


def validate_embeddings_artifact(
    *,
    embeddings_path: Path,
    expected_emb_version: str | None = None,
) -> dict[str, Any]:
    rows = _iter_jsonl_rows(embeddings_path, "embeddings")
    required_fields = (
        "customer_id",
        "fs_version",
        "emb_version",
        "policy_version",
        "vector",
    )
    discovered_versions: set[str] = set()
    vector_dim: int | None = None

    for line_number, row in rows:
        for field_name in required_fields:
            if row.get(field_name) in (None, ""):
                _raise(
                    code="DQ_REQUIRED_FIELD_MISSING",
                    dataset="embeddings",
                    path=embeddings_path,
                    detail="required field missing or empty",
                    line_number=line_number,
                    field=field_name,
                )

        vector = row["vector"]
        if not isinstance(vector, list) or not vector:
            _raise(
                code="DQ_VECTOR_INVALID",
                dataset="embeddings",
                path=embeddings_path,
                detail="vector must be a non-empty list",
                line_number=line_number,
                field="vector",
            )
        for value in vector:
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                _raise(
                    code="DQ_VECTOR_INVALID",
                    dataset="embeddings",
                    path=embeddings_path,
                    detail="vector contains non-finite or non-numeric value",
                    line_number=line_number,
                    field="vector",
                )

        if vector_dim is None:
            vector_dim = len(vector)
        elif vector_dim != len(vector):
            _raise(
                code="DQ_VECTOR_DIMENSION_MISMATCH",
                dataset="embeddings",
                path=embeddings_path,
                detail=f"expected vector size {vector_dim}, got {len(vector)}",
                line_number=line_number,
                field="vector",
            )

        discovered_versions.add(str(row["emb_version"]))

    if len(discovered_versions) != 1:
        _raise(
            code="DQ_EMBEDDING_VERSION_MIXED",
            dataset="embeddings",
            path=embeddings_path,
            detail=f"mixed emb_version values detected: {sorted(discovered_versions)}",
        )
    emb_version = next(iter(discovered_versions))
    if expected_emb_version and emb_version != expected_emb_version:
        _raise(
            code="DQ_EMBEDDING_VERSION_MISMATCH",
            dataset="embeddings",
            path=embeddings_path,
            detail=(
                f"expected emb_version={expected_emb_version!r}, "
                f"runtime={emb_version!r}"
            ),
        )

    return {
        "status": "passed",
        "dataset": "embeddings",
        "path": str(embeddings_path),
        "record_count": len(rows),
        "vector_size": vector_dim or 0,
        "emb_version": emb_version,
    }
