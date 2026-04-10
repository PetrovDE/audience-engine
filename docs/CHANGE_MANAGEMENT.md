# Change Management (Control Plane v1)

## Purpose
Define approval, promotion, and rollback governance for control-plane changes across features, models, embeddings, and policies.

## Governance Principles
1. Immutable-by-version artifacts.
2. No production promotion without explicit approval evidence.
3. Fail-closed on missing required controls or required inputs.
4. Promotion and rollback actions must be fully auditable with actor identity.

## Change Types and Required Evidence
| Change type | Minimum evidence | Required approvers | Promotion blocker examples |
| --- | --- | --- | --- |
| `FeatureSetVersion` | Contract validation, allowlist/PII checks, compatibility review | Data Engineer + Admin/Operator | PII exposure risk, schema mismatch, incompatible downstream embedding contract |
| `ModelVersion` / `EmbeddingModelVersion` | Compatibility check, quality/performance baseline, timeout policy | ML Analyst + Admin/Operator | Missing lineage metadata, unstable runtime behavior, unapproved fallback |
| `PolicyVersion` | Rule validation, reason-code binding validation, required-input checks | Data Engineer/ML Analyst (review) + Admin/Operator | Invalid rule bindings, fail-open behavior, missing required datasets |
| `AudienceDefinitionVersion` | Compatibility with active fs/emb/policy versions, business intent review | Campaign User owner + Admin/Operator | References deprecated/inactive versions, undefined delivery constraints |
| `IndexGeneration` promotion | Validation success, lifecycle audit trail, rollback target availability | Admin/Operator | Validation failure, missing rollback source, alias action audit failure |

## Standard Promotion Workflow
1. Author new immutable version artifact (`draft`).
2. Run validation and capture evidence.
3. Perform cross-entity compatibility check.
4. Record approvals in change record.
5. Promote to `active` (or for index: promote alias to validated generation).
6. Monitor run and delivery integrity after promotion.
7. If degradation is detected, execute audited rollback.

## Rollback Governance
Rollback is a controlled pointer change, not payload mutation.

- Versioned metadata rollback: reactivate a previously validated/deprecated compatible version.
- Index rollback: alias switch to previous promoted generation via lifecycle service.
- Every rollback requires:
  - explicit incident reason,
  - actor identity,
  - timestamp,
  - affected run window,
  - post-rollback verification record.

## Blockers vs Non-Blocking Gaps
| Classification | Definition | Examples |
| --- | --- | --- |
| Blocker | Must stop promotion | Missing required lineage fields, failed validation, readiness false for required connector, unresolved policy fail-closed errors |
| Non-blocking gap | Promotion can proceed with documented risk | Missing optional explain-helper model, minor documentation lag, non-critical UI display inconsistency |

## Minimum Audit Expectations
Every promoted or rolled-back change must leave an auditable trail containing:

1. Change type and version id.
2. Actor role and identity.
3. Validation evidence reference.
4. Approval decision and timestamp.
5. Linked run lineage impact (`run_id` window or campaign scope).
6. Rollback decision, if executed.

Primary audit records remain Postgres append-only tables plus lifecycle audit logs.

## Relationship to Readiness and Delivery Integrity
- Readiness gates (`runtime_runnable` and readiness mode semantics) are preconditions for promotion into active run defaults.
- Delivery integrity checks must confirm that selected integration/export/delivery paths are compatible before run activation.
- Change approval is incomplete unless both lineage integrity and delivery integrity are confirmed.

## Implemented vs Target-State Notes
Implemented as of 2026-04-10:
- Index lifecycle audit and run audit lineage are durable and append-only.
- Policy and integration readiness controls already enforce several fail-closed conditions.

Target-state:
- Unified change-record object linking approvals, validations, promotions, and rollback outcomes across all control-plane entity families.
- Consistent workflow tooling for non-index metadata promotions equivalent to lifecycle service behavior.
