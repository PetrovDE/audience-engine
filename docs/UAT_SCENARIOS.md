# UAT Scenario Checklist (Stage 6)

## Purpose
Provide compact, role-oriented UAT scenarios that match the current implementation.

## Shared Preconditions
- Local environment is running (`make dev-up` and retrieval API started with `infra/.env.local`).
- Operator UI login is configured (`OPERATOR_UI_USERNAME`, `OPERATOR_UI_PASSWORD`).
- Registry/bootstrap data exists for at least one runnable profile and delivery target.

## Scenario 1: Campaign User Run and Outcome Review
### Preconditions
- Defaults already set to approved policy/profile/target.
- At least one runnable integration profile and delivery target.

### Steps
1. Open `/operator/trigger-run`.
2. Enter `campaign_id` and `requested_size`; keep overrides empty.
3. Submit run.
4. Open `/operator/recent-runs` and confirm run appears with expected status.
5. Open `/operator/delivery` (filter by `run_id`) to verify delivery summary and records.

### Expected Result
- Trigger returns `Run finished` with `run_id`.
- Recent runs show the run with expected policy/integration/delivery values.
- Delivery shows attempts and records for that `run_id`.

### Where to Look if It Fails
- `/operator/trigger-run` error panel for immediate cause.
- `/operator/recent-runs` `last_failure` column for run-level failures.
- `/operator/readiness` for non-runnable connectors/targets.

## Scenario 2: Data Engineer Defaults and Readiness Validation
### Preconditions
- Multiple profiles/targets exist, including at least one implemented entry.

### Steps
1. Open `/operator/readiness`; verify required profile and delivery target are runnable.
2. Open `/operator/defaults`; set policy/profile/target to implemented entries.
3. Save defaults.
4. Re-open `/operator/dashboard` and confirm selected defaults match the saved values.

### Expected Result
- Readiness page clearly indicates runnable vs non-runnable entries.
- Defaults save succeeds and reflects selected values.
- Dashboard selected-defaults panel matches saved state.

### Where to Look if It Fails
- `/operator/defaults` validation error.
- Readiness table `runtime_validation_errors`.
- Integration profile or delivery target registry metadata.

## Scenario 3: ML Analyst Governance and Explain Review
### Preconditions
- At least one version exists in `/operator/control-plane/versions`.
- Optional: known `run_id` + `customer_id` pair for explain lookup.

### Steps
1. Open `/operator/control-plane/versions` and filter to relevant entity family.
2. Open a version detail page.
3. Review promotion readiness: blockers, non-blocking gaps, and checks.
4. Record evidence with `operator_note` or other evidence type.
5. Open `/operator/explain-audit` and run a policy explain lookup.

### Expected Result
- Detail page shows clear governance readiness outcome.
- Evidence submission appears in the promotion evidence table.
- Explain lookup returns decision details when row exists.

### Where to Look if It Fails
- Governance blockers/check rows on detail page.
- Evidence form validation errors (`details_json` format).
- Explain lookup notice/error for missing decision or invalid `run_id`.

## Scenario 4: Admin/Operator Lifecycle and Governance Control
### Preconditions
- Version lifecycle transitions are available for a selected entity version.
- Governance evidence exists (or intentional blocker exists) for activation test.

### Steps
1. Open `/operator/control-plane/versions` and navigate to version detail.
2. Attempt `Validate` then `Activate` as appropriate.
3. If activation is blocked, review blocker message and record required evidence.
4. Retry activation after evidence is recorded.
5. Confirm lifecycle and promotion decision records update.

### Expected Result
- Invalid transitions are blocked with explicit error.
- Activation is blocked when governance is not ready.
- Successful activation writes decision and lifecycle audit trail.

### Where to Look if It Fails
- Detail page blocker message and checks table.
- Promotion decisions and recent actions tables.
- `/operator/explain-audit` lifecycle audit summary for cross-check.
