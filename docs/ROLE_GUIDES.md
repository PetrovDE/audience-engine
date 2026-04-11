# Role Guides (Control Plane v1)

## Purpose
Define control-plane responsibilities, allowed actions, ownership boundaries, and handoffs by role.

## Stage 7 UAT Execution Note
- Use `/operator/dashboard` as the UAT start page and review the UAT status panel before executing role scenarios.
- Role guidance in the UI is routing guidance for shared-operator sessions, not persona-isolated authorization.

## Role Matrix
| Role | Core responsibility | Owned entities | Primary handoff |
| --- | --- | --- | --- |
| Campaign User | Request and consume approved audiences | `AudienceDefinitionVersion` inputs at run time (business intent), campaign parameters | Receives approved defaults from Admin/Operator |
| Data Engineer | Govern feature/integration/export readiness | `FeatureSetVersion`, `ExportProfile`, data contracts, source readiness | Hands validated feature/export changes to ML Analyst and Admin/Operator |
| ML Analyst | Govern model/embedding/ranking policy fit | `ModelVersion`, `EmbeddingModelVersion`, scoring/reranking settings | Hands validated model choices to Admin/Operator for activation |
| Admin/Operator | Control runtime defaults, promotions, rollback, and incident response | Active selections, index promotions, run orchestration, audit review | Provides stable executable defaults to Campaign User |

## Allowed Actions by Role
| Action | Campaign User | Data Engineer | ML Analyst | Admin/Operator |
| --- | --- | --- | --- | --- |
| Trigger audience run | Yes (with approved versions/defaults) | Yes | Yes | Yes |
| Change control-plane defaults | No | Limited (proposal) | Limited (proposal) | Yes |
| Activate/deprecate feature versions | No | Yes | Review | Approve/promote |
| Activate/deprecate model/embedding versions | No | Review | Yes | Approve/promote |
| Activate/deprecate policy versions | No | Review | Review | Approve/promote |
| Promote/rollback index alias | No | No | No | Yes |
| View explain/audit lineage | Read for owned campaigns | Yes | Yes | Yes |

## What Each Role Must Understand in the Product/UI

### Campaign User
- How to trigger runs safely with approved defaults.
- How to read run outcome summaries and delivery status.
- How to request exception handling when a run fails policy/readiness gates.

### Data Engineer
- Feature and integration readiness states (`runtime_runnable`, readiness mode semantics).
- Data contract compatibility and fail-closed behavior.
- Export profile constraints and delivery target compatibility.

### ML Analyst
- `emb_version` composition (`fs_version + prompt_version + model_version`).
- Model/version compatibility with feature sets and policy gates.
- Quality/performance evidence needed for activation or rollback recommendation.
- Where to execute in current UI: `/operator/control-plane/versions` (including `embedding_model_versions` family), `/operator/explain-audit`, `/operator/readiness`.

### Admin/Operator
- End-to-end run orchestration across API/UI and Airflow operator DAG path.
- Lifecycle mutation controls (`validate/promote/rollback`) and audit responsibilities.
- Incident operations for fail-closed conditions, promotions, and controlled rollback.

## Implemented vs Target-State Notes
Implemented as of 2026-04-11:
- Runtime/API enforces role separation primarily between campaign and admin API keys.
- Operator UI is operational but currently uses one operator login model, not four fully isolated personas.

Target-state:
- Persona-specific UI scopes and policy-backed permissions for Campaign User, Data Engineer, ML Analyst, and Admin/Operator.
- Explicit approval workflow routing by role for lifecycle transitions.
