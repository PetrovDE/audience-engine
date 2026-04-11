# UAT Scenario Checklist (Stage 7)

## Purpose
Provide compact, implementation-accurate UAT scenarios that can be executed directly in the current Operator Console.

## Shared Preconditions
- Local environment is running (`make dev-up` and retrieval API started with `infra/.env.local`).
- Operator UI login is configured (`OPERATOR_UI_USERNAME`, `OPERATOR_UI_PASSWORD`).
- Bootstrap/registry data exists for at least one implemented and runnable profile plus delivery target.
- Reviewer starts from `/operator/dashboard` and checks the UAT status panel before running scenarios.

## Scenario 1: Campaign User Run and Outcome Review
### Preconditions
- Defaults are set to approved policy/profile/target.
- At least one integration profile and delivery target show `runtime_runnable=true`.

### Steps
1. Open `/operator/trigger-run`.
2. Enter `campaign_id` and `requested_size`; keep overrides empty for default-path validation.
3. Submit run and capture the returned `run_id` from the notice/result payload.
4. Open `/operator/recent-runs` and confirm the run appears with expected status and selected versions.
5. Open `/operator/delivery` and filter by the `run_id` to validate summary, attempts, and records.

### Expected Result
- Trigger returns `Run finished` and includes `run_id` when available.
- Recent Runs shows expected policy/integration/delivery values for the run.
- Delivery page shows job and attempt evidence for that `run_id`.

### Where to Look if It Fails
- `/operator/trigger-run` error panel for immediate cause.
- `/operator/recent-runs` `last_failure` column (rendered from run error payload).
- `/operator/readiness` for non-runnable connectors/profiles/targets.

## Scenario 2: Data Engineer Defaults and Readiness Validation
### Preconditions
- Multiple profiles/targets exist with at least one implemented entry.

### Steps
1. Open `/operator/readiness` and verify required profile and target are runnable.
2. Open `/operator/defaults` and set policy/profile/target to implemented entries.
3. Save defaults.
4. Open `/operator/dashboard` and confirm selected defaults reflect saved values.

### Expected Result
- Readiness page clearly separates runnable vs non-runnable rows.
- Defaults save succeeds.
- Dashboard selected-defaults panel matches persisted defaults.

### Where to Look if It Fails
- `/operator/defaults` save/validation error.
- Readiness table `runtime_validation_errors`.
- Registry metadata for profile or delivery target.

## Scenario 3: ML Analyst Governance and Explain Review
### Preconditions
- At least one version exists in `/operator/control-plane/versions`.
- Optional but recommended: known `run_id` + `customer_id` for explain lookup.

### Steps
1. Open `/operator/control-plane/versions` and filter to the relevant family/entity key.
2. Open version detail.
3. Review promotion readiness (`blockers`, `non-blocking`, `checks`).
4. Record evidence (`operator_note` or other evidence type).
5. Open `/operator/explain-audit` and run a policy explain lookup.

### Expected Result
- Version detail shows governance readiness with explicit blockers/checks.
- Evidence submission appears in promotion evidence table.
- Explain lookup returns decision details when a row exists.

### Where to Look if It Fails
- Governance blockers/checks table on detail page.
- Evidence form validation errors (`details_json` must decode to JSON object).
- Explain lookup notice/error for missing decision row or invalid `run_id`.

## Scenario 4: Admin/Operator Lifecycle and Governance Control
### Preconditions
- Lifecycle transitions are available for selected entity version.
- Governance evidence exists (or blocker is intentionally reproduced for negative test).

### Steps
1. Open `/operator/control-plane/versions` and navigate to version detail.
2. Run `Validate` and then attempt `Activate`.
3. If activation is blocked, review blocker message and record missing evidence.
4. Retry activation after evidence is added.
5. Verify promotion decisions and lifecycle actions update.

### Expected Result
- Invalid transitions are blocked with explicit error.
- Activation is blocked when governance is not ready.
- Successful activation writes promotion decision + lifecycle audit trail.

### Where to Look if It Fails
- Detail page blocker message and checks table.
- Promotion Decisions and Recent Actions sections.
- `/operator/explain-audit` lifecycle audit summary for cross-check.

## Scenario 5: Provider/Model Visibility Journey
### Preconditions
- At least one model or embedding model version exists in registry (or seeded fixture data).

### Steps
1. Open `/operator/control-plane/versions?entity_type=embedding_model_versions`.
2. Confirm provider/model-related metadata is visible in list/detail flows.
3. Open `/operator/readiness` and confirm readiness context is available alongside provider/model review workflow.

### Expected Result
- Embedding/model family appears in control-plane list options and renders rows/details.
- Detail page shows key metadata fields for provider/model version rows when present.
- Reviewer can use readiness and control-plane pages together without route/name ambiguity.

### Where to Look if It Fails
- Control-plane list filter and detail metadata panel.
- Role journey guidance panel for `/operator/control-plane/versions`.
- Registry seed/bootstrap data for provider/model families.

## Known Caveats (Current Implementation)
- Operator UI uses one shared operator login; full persona-isolated RBAC is not implemented in Stage 7.
- Planned integration/profile/target rows are intentionally visible but non-runnable and disabled where applicable.
- Explain lookup requires both `run_id` and `customer_id`; missing inputs return explicit guidance.
