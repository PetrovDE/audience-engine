# Policy Engine Specification (M2)

## Purpose
This document defines the M2 functional specification for the Policy Engine gate that is mandatory before production audience export.

## Scope
- Defines Policy Engine API contracts and payloads.
- Defines YAML-based rule specification.
- Defines required datasets and validation expectations.
- Defines audit model and lineage requirements.
- Defines baseline test scenarios and expected outcomes.
- Defines rejection reason taxonomy mapped to governed reason codes.

Out of scope:
- Runtime service implementation.
- Infrastructure and deployment details.
- Data migration execution.

## Alignment and Constraints
This spec inherits Architecture V3 and Governance Pack constraints:
- Policy Engine is a mandatory production export gate.
- PII must not be embedded or logged.
- Version contracts are required in audit lineage.
- Policy artifacts are immutable by version.

Required version contracts in request, response, and audit:
- `fs_version`
- `emb_version`
- `policy_version`
- `index_alias` (and resolved index generation/version)

## API Contracts

### 1) Evaluate Candidates
`POST /v1/policy/evaluate`

Purpose:
Evaluate ranked candidate rows for suppression/eligibility/risk/conflict/quota checks and return per-customer decisions.

Request schema:
```yaml
request_id: string                  # caller-generated idempotency key
run_id: string                      # campaign run id
campaign_id: string
channel: string                     # email|sms|push|other
evaluation_ts: timestamp
versions:
  fs_version: string
  emb_version: string
  policy_version: string
  index_alias: string
  index_version: string
inputs:
  candidate_set_ref: string         # logical table/object reference
  datasets:
    blacklist_ref: string
    optout_ref: string
    comm_history_ref: string
options:
  fail_closed: bool                 # default true
  max_reasons_per_customer: int     # default 5
```

Response schema:
```yaml
request_id: string
run_id: string
campaign_id: string
policy_version: string
summary:
  total_candidates: int
  approved_count: int
  rejected_count: int
  rejection_rate: float
results:
  - customer_id: string
    decision: string                # approve|reject
    reasons:
      - reason_code: string
        reason_class: string
        message: string
        rule_id: string
    evaluated_at: timestamp
errors:                             # populated when partial/failed eval occurs
  - code: string
    message: string
```

Behavioral contract:
- If `fail_closed=true` and a required dataset is unavailable, decision must default to `reject` with system reason code.
- Multiple rejecting rules may match a customer; output reasons are ordered by `priority` then rule id.
- API must be idempotent by (`request_id`, `policy_version`).

### 2) Validate Policy Definition
`POST /v1/policy/validate`

Purpose:
Validate YAML rule file and reason-code bindings before activation.

Request schema:
```yaml
policy_version: string
policy_yaml: string
reason_dictionary_ref: string
```

Response schema:
```yaml
policy_version: string
valid: bool
errors:
  - path: string
    code: string
    message: string
warnings:
  - path: string
    code: string
    message: string
```

### 3) Explain Decision
`GET /v1/policy/decisions/{run_id}/{customer_id}`

Purpose:
Retrieve stored policy decision and reasons for audit, support, and troubleshooting.

Response schema:
```yaml
run_id: string
customer_id: string
decision: string
reasons:
  - reason_code: string
    reason_class: string
    message: string
    rule_id: string
audit_ref: string
```

## Rule Format (YAML-Based)

### File location and versioning
- Registry location: `governance/policies/policy_registry.yaml`.
- Each semantic change requires new `policy_version` and changelog update.
- Rules must bind only to valid codes in `governance/dictionaries/reason_codes.yaml`.

### Canonical rule schema
```yaml
policy_version: policy_credit_v2
status: draft|active|retired
scope: production_export_gate
metadata:
  owner: policy-engine
  updated_at: YYYY-MM-DD
inputs:
  raw_contract: governance/contracts/raw.yaml
  feature_mart_contract: governance/contracts/feature_mart.yaml
  reason_codes: governance/dictionaries/reason_codes.yaml
rules:
  - id: suppress_do_not_contact
    description: Suppress customers opted out of contact.
    enabled: true
    priority: 100
    when: do_not_contact_flag == true
    action: suppress                    # suppress|reject|approve_override
    reason_code: SUPPRESS_DNC
    stop_on_match: false
  - id: require_minimum_tenure
    enabled: true
    priority: 200
    when: customer_tenure_months < 3
    action: suppress
    reason_code: ELIGIBILITY_TENURE_LT_3M
```

Rule constraints:
- `id` unique within `policy_version`.
- `priority` integer, lower executes first.
- `when` expression may only reference fields present in governed contracts.
- `reason_code` must exist in dictionary and class-compatible with action.
- `approve_override` is optional and must be explicitly enabled by policy metadata.

## Required Datasets

Policy evaluation requires these datasets at run time.

### 1) Blacklists dataset
Minimum columns:
- `customer_id` (string, required)
- `blacklist_type` (string, required)
- `active_flag` (bool, required)
- `effective_from_ts` (timestamp, required)
- `effective_to_ts` (timestamp, optional)
- `source_system` (string, required)

Usage:
- Hard suppression for active blacklist records in evaluation window.

### 2) Opt-outs dataset
Minimum columns:
- `customer_id` (string, required)
- `channel` (string, required)
- `optout_flag` (bool, required)
- `optout_ts` (timestamp, required)
- `source_system` (string, required)

Usage:
- Channel-aware suppression.
- Must reconcile with `do_not_contact_flag` in feature mart.

### 3) Communication history dataset
Minimum columns:
- `customer_id` (string, required)
- `campaign_id` (string, required)
- `channel` (string, required)
- `contact_ts` (timestamp, required)
- `outcome` (string, optional)

Usage:
- Frequency caps and conflict checks.
- Daily/rolling-window quota enforcement.

### Dataset quality requirements
- Freshness SLA: data timestamps must be within policy-configured staleness threshold.
- Referential integrity: `customer_id` must join against candidate set.
- Null handling: missing required fields trigger fail-closed behavior when enabled.

## Audit Model

### Principles
- Immutable decision records for every evaluated customer.
- Full version lineage across features, embeddings, policy, and index.
- No PII in audit payloads beyond permitted identifiers.

### Audit entities

1. `policy_run_audit`
```yaml
run_id: string
request_id: string
campaign_id: string
evaluation_ts: timestamp
versions:
  fs_version: string
  emb_version: string
  policy_version: string
  index_alias: string
  index_version: string
dataset_refs:
  blacklist_ref: string
  optout_ref: string
  comm_history_ref: string
summary:
  total_candidates: int
  approved_count: int
  rejected_count: int
status: string                       # success|partial_failure|failure
```

2. `policy_decision_audit`
```yaml
run_id: string
customer_id: string
decision: string                     # approve|reject
reasons:
  - reason_code: string
    rule_id: string
    priority: int
evaluated_at: timestamp
```

### Retention and access
- Retention target: 400 days minimum for production decisions.
- Access: read-only to audit/compliance roles, append-only for service role.

## Test Scenarios

### Functional scenarios
1. DNC suppression:
- Input has `do_not_contact_flag=true`.
- Expected: reject with `SUPPRESS_DNC`.

2. Employee suppression:
- Input has `is_employee_flag=true`.
- Expected: reject with `SUPPRESS_EMPLOYEE`.

3. Tenure eligibility:
- Input has `customer_tenure_months=2`.
- Expected: reject with `ELIGIBILITY_TENURE_LT_3M`.

4. Delinquency risk:
- Input has `delinquency_12m_count=3`.
- Expected: reject with `RISK_DELINQ_GT_2`.

5. Quota reached:
- Comm history exceeds daily campaign cap.
- Expected: reject with `QUOTA_DAILY_CAMPAIGN_REACHED`.

6. Campaign conflict:
- Customer active in conflicting campaign.
- Expected: reject with `CONFLICT_ACTIVE_CAMPAIGN`.

7. Multi-hit ordering:
- Customer matches multiple rules.
- Expected: reasons sorted by priority; deterministic output.

8. Dataset unavailable + fail-closed:
- Missing opt-out dataset and `fail_closed=true`.
- Expected: reject with system/data-availability reason; run status partial/failure.

### Validation scenarios
- Invalid rule expression references unknown field.
- Unknown `reason_code` binding.
- Duplicate rule IDs.
- Non-monotonic/duplicate priorities (warning or error per validator policy).

## Rejection Reason Taxonomy

Source dictionary: `governance/dictionaries/reason_codes.yaml`.

### Classes
- `suppression`: legal/compliance and hard exclusion.
- `eligibility`: threshold or product-fit gating.
- `risk`: policy risk controls.
- `quota`: contact-frequency limits.
- `conflict`: campaign concurrency conflicts.

### Current required codes
- `SUPPRESS_DNC` (suppression)
- `SUPPRESS_EMPLOYEE` (suppression)
- `ELIGIBILITY_TENURE_LT_3M` (eligibility)
- `RISK_DELINQ_GT_2` (risk)
- `QUOTA_DAILY_CAMPAIGN_REACHED` (quota)
- `CONFLICT_ACTIVE_CAMPAIGN` (conflict)

### Extension rules
- New codes must declare class, message, owner, and effective version.
- Reused codes must preserve semantic meaning across versions.
- Deprecated codes remain queryable for historical audits.

## Acceptance Criteria (M2 Spec)
- API contracts are documented and unambiguous.
- Rule YAML schema supports deterministic evaluation and reason binding.
- Required datasets and minimum columns are defined.
- Audit model captures immutable per-run and per-customer lineage.
- Test scenarios cover suppression, eligibility, risk, quota, conflict, and failure modes.
- Rejection taxonomy is aligned with governed reason-code dictionary.
