import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

import yaml

from .metrics import record_policy_reject_reason

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_REGISTRY_PATH = ROOT / "governance" / "policies" / "policy_registry.yaml"
DEFAULT_REASON_CODES_PATH = ROOT / "governance" / "dictionaries" / "reason_codes.yaml"


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _read_blacklist(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _truthy(value: Any) -> bool:
    return bool(value)


def _get_var(context: Dict[str, Any], path: str, default: Any = None) -> Any:
    if not isinstance(path, str):
        return default
    if not path:
        return context
    current: Any = context
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _normalize_rule_expr(raw_expr: Any) -> Any:
    if isinstance(raw_expr, dict):
        return raw_expr
    if not isinstance(raw_expr, str):
        raise ValueError("rule 'when' must be a JSONLogic object or legacy string")
    tokens = raw_expr.strip().split()
    if len(tokens) != 3:
        raise ValueError(
            f"unsupported legacy rule expression '{raw_expr}'. "
            "Expected a JSONLogic object."
        )
    field, op, value_token = tokens
    value: Any
    lower = value_token.lower()
    if lower == "true":
        value = True
    elif lower == "false":
        value = False
    else:
        try:
            value = int(value_token)
        except ValueError:
            try:
                value = float(value_token)
            except ValueError:
                value = value_token.strip("'\"")
    if op not in {"==", "!=", ">", "<", ">=", "<="}:
        raise ValueError(
            f"unsupported legacy operator '{op}'. Expected a JSONLogic object."
        )
    return {op: [{"var": field}, value]}


def _eval_jsonlogic(expr: Any, context: Dict[str, Any]) -> Any:
    if isinstance(expr, (bool, int, float)) or expr is None:
        return expr
    if isinstance(expr, str):
        return expr
    if isinstance(expr, list):
        return [_eval_jsonlogic(v, context) for v in expr]
    if not isinstance(expr, dict):
        raise ValueError(f"unsupported JSONLogic node: {type(expr)!r}")
    if len(expr) != 1:
        raise ValueError("JSONLogic node must contain exactly one operator")

    op, raw_args = next(iter(expr.items()))
    args = raw_args if isinstance(raw_args, list) else [raw_args]

    if op == "var":
        key = args[0] if args else ""
        default = args[1] if len(args) > 1 else None
        return _get_var(context, key, default)
    if op in {"==", "!=", ">", "<", ">=", "<="}:
        if len(args) != 2:
            raise ValueError(f"operator '{op}' expects 2 args")
        left = _eval_jsonlogic(args[0], context)
        right = _eval_jsonlogic(args[1], context)
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == ">":
            return left > right
        if op == "<":
            return left < right
        if op == ">=":
            return left >= right
        return left <= right
    if op == "and":
        return all(_truthy(_eval_jsonlogic(arg, context)) for arg in args)
    if op == "or":
        return any(_truthy(_eval_jsonlogic(arg, context)) for arg in args)
    if op == "!":
        if len(args) != 1:
            raise ValueError("operator '!' expects 1 arg")
        return not _truthy(_eval_jsonlogic(args[0], context))
    if op == "in":
        if len(args) != 2:
            raise ValueError("operator 'in' expects 2 args")
        needle = _eval_jsonlogic(args[0], context)
        haystack = _eval_jsonlogic(args[1], context)
        if isinstance(haystack, str):
            return str(needle) in haystack
        return needle in (haystack or [])
    raise ValueError(f"unsupported JSONLogic operator: {op}")


def _load_reason_dictionary(reason_codes_path: Path) -> Dict[str, Dict[str, str]]:
    with reason_codes_path.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    out: Dict[str, Dict[str, str]] = {}
    for item in payload.get("codes", []):
        code = item.get("code")
        if code:
            out[code] = {
                "class": item.get("class", "unknown"),
                "message": item.get("message", ""),
            }
    return out


def _load_policy(policy_version: str, policy_registry_path: Path) -> Dict[str, Any]:
    with policy_registry_path.open("r", encoding="utf-8") as f:
        registry = yaml.safe_load(f) or {}
    policies = registry.get("policies", [])
    for policy in policies:
        if policy.get("policy_version") == policy_version:
            return policy
    raise ValueError(
        f"Unknown policy_version '{policy_version}' in {policy_registry_path}"
    )


def _history_by_customer(comm_history_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    rows = _read_jsonl(comm_history_path)
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cid = row.get("customer_id")
        if cid:
            grouped[str(cid)].append(row)
    return grouped


def _build_candidate_context(
    candidate: Dict[str, Any],
    *,
    blacklist: Set[str],
    history_rows: Iterable[Dict[str, Any]],
    now_ts: datetime,
    channel: str,
    campaign_id: str | None,
    conflicting_campaign_ids: Set[str],
    refusal_cooldown_days: int,
) -> Dict[str, Any]:
    cid = str(candidate["customer_id"])
    contacts_7d = 0
    contacts_30d = 0
    contacts_90d = 0
    cooldown_active = False
    conflict_active = False
    cutoff_7d = now_ts - timedelta(days=7)
    cutoff_30d = now_ts - timedelta(days=30)
    cutoff_90d = now_ts - timedelta(days=90)
    refusal_cutoff = now_ts - timedelta(days=refusal_cooldown_days)
    refusal_outcomes = {"refused", "declined", "opt_out", "optout", "unsubscribed"}

    for row in history_rows:
        if row.get("channel") not in (None, channel):
            continue
        ts = _parse_ts(row.get("contact_ts"))
        if not ts:
            continue
        if ts >= cutoff_90d:
            contacts_90d += 1
        if ts >= cutoff_30d:
            contacts_30d += 1
        if ts >= cutoff_7d:
            contacts_7d += 1
        outcome = str(row.get("outcome", "")).lower()
        if outcome in refusal_outcomes and ts >= refusal_cutoff:
            cooldown_active = True
        row_campaign = row.get("campaign_id")
        active_flag = bool(row.get("active_flag", outcome == "active"))
        if not row_campaign:
            continue
        if campaign_id and str(row_campaign) == str(campaign_id):
            continue
        if conflicting_campaign_ids and str(row_campaign) not in conflicting_campaign_ids:
            continue
        if active_flag:
            conflict_active = True

    return {
        **candidate,
        "customer_id": cid,
        "is_blacklisted": cid in blacklist,
        "opt_out_flag": bool(candidate.get("opt_out_flag", False)),
        "legal_suppression_flag": bool(candidate.get("legal_suppression_flag", False)),
        "is_employee_flag": bool(candidate.get("is_employee_flag", False)),
        "customer_tenure_months": int(candidate.get("customer_tenure_months", 9999)),
        "delinquency_12m_count": int(candidate.get("delinquency_12m_count", 0)),
        "contacts_last_7d": contacts_7d,
        "contacts_last_30d": contacts_30d,
        "contacts_last_90d": contacts_90d,
        "cooldown_after_refusal_active": cooldown_active,
        "campaign_conflict_active": conflict_active,
    }


def evaluate_policy(
    candidates: List[Dict[str, Any]],
    *,
    policy_version: str,
    blacklist_path: Path,
    comm_history_path: Path,
    policy_registry_path: Path = DEFAULT_POLICY_REGISTRY_PATH,
    reason_codes_path: Path = DEFAULT_REASON_CODES_PATH,
    channel: str = "email",
    campaign_id: str | None = None,
    conflicting_campaign_ids: Set[str] | None = None,
    requested_size: int | None = None,
    refusal_cooldown_days: int = 30,
) -> Dict[str, Any]:
    policy = _load_policy(policy_version=policy_version, policy_registry_path=policy_registry_path)
    reason_dict = _load_reason_dictionary(reason_codes_path=reason_codes_path)
    rules = sorted(
        [
            r
            for idx, r in enumerate(policy.get("rules", []))
            if r.get("enabled", True)
            for _ in [r.setdefault("priority", 1000 + idx)]
        ],
        key=lambda r: (int(r.get("priority", 1000)), str(r.get("id", ""))),
    )

    blacklist = _read_blacklist(blacklist_path)
    history = _history_by_customer(comm_history_path)
    now_ts = datetime.now(timezone.utc)
    conflicts = conflicting_campaign_ids or set()

    reason_counts: Counter[str] = Counter()
    results: List[Dict[str, Any]] = []
    approved_candidates: List[Dict[str, Any]] = []
    for item in candidates:
        cid = str(item["customer_id"])
        context = _build_candidate_context(
            item,
            blacklist=blacklist,
            history_rows=history.get(cid, []),
            now_ts=now_ts,
            channel=channel,
            campaign_id=campaign_id,
            conflicting_campaign_ids=conflicts,
            refusal_cooldown_days=refusal_cooldown_days,
        )
        reasons: List[Dict[str, Any]] = []
        for rule in rules:
            expr = _normalize_rule_expr(
                rule.get("when_jsonlogic", rule.get("when"))
            )
            matched = bool(_eval_jsonlogic(expr, context))
            if not matched:
                continue
            action = rule.get("action", "suppress")
            if action not in {"suppress", "reject"}:
                continue
            reason_code = rule.get("reason_code")
            if not reason_code:
                raise ValueError(f"Rule '{rule.get('id')}' missing reason_code")
            if reason_code not in reason_dict:
                raise ValueError(
                    f"Rule '{rule.get('id')}' references unknown reason_code '{reason_code}'"
                )
            reasons.append(
                {
                    "reason_code": reason_code,
                    "reason_class": reason_dict[reason_code]["class"],
                    "message": reason_dict[reason_code]["message"],
                    "rule_id": rule.get("id", ""),
                }
            )
            if rule.get("stop_on_match", False):
                break

        for reason in reasons:
            reason_code = reason["reason_code"]
            reason_counts[reason_code] += 1
            record_policy_reject_reason(reason_code)

        decision = "reject" if reasons else "approve"
        result_row = {
            "customer_id": cid,
            "decision": decision,
            "reasons": reasons,
            "score": float(item.get("score", 0.0)),
        }
        results.append(result_row)
        if decision == "approve":
            approved_candidates.append(result_row)

    selected = sorted(approved_candidates, key=lambda r: r["score"], reverse=True)
    if requested_size is not None:
        selected = selected[: max(requested_size, 0)]
    selected_customer_ids = {row["customer_id"] for row in selected}
    for row in results:
        row["selected"] = row["customer_id"] in selected_customer_ids and row["decision"] == "approve"

    rejected_count = sum(1 for r in results if r["decision"] == "reject")
    approved_count = len(results) - rejected_count
    return {
        "policy_version": policy_version,
        "summary": {
            "total_candidates": len(results),
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "reject_reason_counts": dict(reason_counts),
            "requested_size": requested_size,
            "selected_count": len(selected),
        },
        "rejection_summary": dict(reason_counts),
        "selected": [
            {
                "customer_id": row["customer_id"],
                "score": row["score"],
            }
            for row in selected
        ],
        "results": results,
    }
