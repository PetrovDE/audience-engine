# UAT Role Flows (Stage 6)

## Purpose
Provide a compact, implementation-accurate guide for internal UAT participants using the current Operator Console and control-plane governance surfaces.

## Scope and Honesty
- Current UI uses a shared operator login surface with role-oriented guidance.
- Full persona-isolated RBAC is not implemented in this stage.
- Use this guide for flow ownership and page routing during UAT.

## Role Responsibilities and Primary Pages
| Role | Owns in UAT | Primary pages | Typical output |
| --- | --- | --- | --- |
| Campaign User | Triggering approved runs and validating outcomes | `/operator/trigger-run`, `/operator/recent-runs`, `/operator/delivery` | Successful run, delivery verification, blocker escalation with `run_id` |
| Data Engineer | Defaults and connector/profile readiness | `/operator/defaults`, `/operator/readiness`, `/operator/control-plane/versions` | Runnable defaults and readiness confirmation |
| ML Analyst | Model/policy governance review and explain evidence | `/operator/control-plane/versions`, `/operator/explain-audit`, `/operator/readiness` | Promotion recommendation or blocker evidence |
| Admin/Operator | Runtime defaults, lifecycle transitions, governance evidence | `/operator/dashboard`, `/operator/control-plane/versions`, `/operator/explain-audit` | Controlled activation/deprecation/rollback decisions with audit trail |

## Happy Path (Normal UAT)
1. Confirm readiness (`runtime_runnable=true`) for required profile and delivery target.
2. Confirm or set defaults on `/operator/defaults`.
3. Review version lifecycle and promotion readiness on `/operator/control-plane/versions`.
4. Trigger run on `/operator/trigger-run`.
5. Validate status in `/operator/recent-runs`.
6. Validate downstream delivery in `/operator/delivery`.
7. Use `/operator/explain-audit` for policy explain or lifecycle/delivery audit evidence.

## Common Blockers and What They Mean
| Surface | Blocker signal | Meaning | First check |
| --- | --- | --- | --- |
| `/operator/readiness` | `runtime_runnable=false` | Required connector/profile/target is not runnable now | `runtime_validation_errors`, `runtime_readiness_mode` |
| `/operator/control-plane/versions` detail | Promotion readiness blocker list | Missing or failing governance evidence for activation | Blocker `code`/`message`, evidence table |
| `/operator/trigger-run` | Run failed error payload | Policy/data quality/readiness precondition failed | Error details and selected versions/defaults |
| `/operator/recent-runs` | `status=failed` or error field populated | Run did not complete successfully | `last_failure`, policy/integration/delivery fields |
| `/operator/delivery` | failed attempts or missing summary/records | Export/delivery stage issue | Attempt details, per-run summary |
| `/operator/explain-audit` | No decision row or missing audit entries | No matching decision or missing downstream evidence | `run_id` format, `customer_id`, audit tables |

## What Governance Evidence Controls Are For
- Prevent activation of versions that do not have sufficient validation/readiness/compatibility evidence.
- Make promotion and rollback decisions traceable by actor, timestamp, and rationale.
- Separate true blockers from documented non-blocking gaps so UAT decisions stay explicit.

## Implemented Now vs Target-State Reminder
- Implemented now: governance readiness checks, evidence recording, promotion decision history, lifecycle action audit.
- Target-state (not implemented in this stage): persona-scoped permissions and workflow-routed approvals per role.
