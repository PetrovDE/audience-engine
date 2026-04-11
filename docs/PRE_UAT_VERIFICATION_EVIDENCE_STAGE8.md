# Stage 8 Verification Evidence (Executed)

Date: 2026-04-11
Environment: local Windows host (`d:\AudienceEngine`), Docker Desktop, `uv`

## 1) Automated Verification Commands

### UAT pack integration tests
```bash
uv run pytest -q tests/integration/test_operator_ui_uat_pack_core.py tests/integration/test_operator_ui_uat_pack_control_plane.py
```
Result: `5 passed`

### Operator UI/control-plane integration tests
```bash
uv run pytest -q tests/integration/test_operator_ui_smoke.py tests/integration/test_operator_ui_role_guidance.py tests/integration/test_operator_ui_control_plane_smoke.py tests/integration/test_operator_ui_control_plane_governance.py
```
Result: `30 passed`

### Control-plane/governance/provider unit+contract slice
```bash
uv run pytest -q tests/unit/test_control_plane_registry.py tests/unit/test_control_plane_registry_bootstrap.py tests/unit/test_control_plane_registry_service.py tests/unit/test_control_plane_promotion_governance.py tests/unit/test_control_plane_integrations.py tests/unit/test_embedding_provider_wiring.py tests/unit/test_embedding_provider_resolution.py tests/unit/test_lifecycle_service.py tests/contracts/test_governance_contracts.py
```
Result: `54 passed`

### Full integration sweep (baseline run before stabilization)
```bash
uv run pytest -q tests/integration
```
Baseline result: `1 failed, 83 passed, 1 skipped`
- Failure was `tests/integration/test_policy_explain_integration.py` due Postgres startup readiness race.

### Post-fix verification for stabilized test
```bash
uv run pytest -q tests/integration/test_policy_explain_integration.py
```
Result after fix: `1 passed`

### Full integration sweep (post-fix re-run)
```bash
uv run pytest -q tests/integration
```
Result: `1 failed, 83 passed, 1 skipped`
- Remaining failure: `tests/integration/test_minimal_slice_smoke.py::test_minimal_slice_smoke_cpu_no_gpu_required`
- Cause observed: MinIO endpoint unavailable in that test's compose bring-up path.

### Smoke + full integration with MinIO explicitly up
```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml up -d minio
uv run pytest -q tests/integration/test_minimal_slice_smoke.py -k cpu
uv run pytest -q tests/integration
```
Result:
- CPU smoke: `1 passed, 1 deselected`
- full integration: `84 passed, 1 skipped`

## 2) Runtime Host-Run Verification

### Infra bring-up and bootstrap
Executed:
```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml up -d
uv run --env-file infra/.env.local python -m pipelines.minimal_slice.control_plane_registry --bootstrap-dev-test
```
Outcome: services started; control-plane bootstrap applied with active seeded versions.

### API host-run startup
Executed:
```bash
uv run --env-file infra/.env.local python -m uvicorn services.retrieval_api.app:app --host 127.0.0.1 --port 8010
```
Outcome: `/healthz` returned HTTP 200 with status `ok`.

### Operator login + navigation
Executed via HTTP calls with session cookies against `http://127.0.0.1:8010`.
Verified HTTP 200 content for:
- `/operator/dashboard`
- `/operator/defaults`
- `/operator/control-plane/versions`
- `/operator/trigger-run`
- `/operator/recent-runs`
- `/operator/delivery`
- `/operator/explain-audit`
- `/operator/readiness`

Login verification:
- `GET /operator/login` -> 200
- `POST /operator/login` -> 303 redirect

### Control-plane provider/model visibility and governance evidence
Executed:
- `GET /operator/control-plane/versions?entity_type=embedding_model_versions&entity_key=local_ollama`
- `GET /operator/control-plane/versions/embedding_model_versions/local_ollama/323a1f02-360f-4464-85ac-e8008ca8b022`
- `POST .../evidence` with `evidence_type=operator_note`

Outcome:
- embedding model row and provider metadata were visible
- evidence submit returned 303 and rendered in detail page

### Trigger run + downstream surfaces
Executed:
- `POST /operator/trigger-run` with `campaign_id=camp_pre_uat_001`, `requested_size=20`
- observed runtime `run_id`: `27bb0d1a-d0eb-4a15-ae43-f9c313a11c59`
- `GET /operator/recent-runs` confirmed run presence
- `GET /operator/delivery?run_id=<run_id>` confirmed delivery detail rendering
- `POST /operator/explain-audit` with `run_id` + `customer_id=cust_00000` returned explain/audit view content

## 3) Executed vs Assumed
Executed directly:
- all commands and runtime checks listed above

Assumed/static only:
- no persona-specific RBAC verification (feature not implemented in current stage)
- no production deployment validation (out of scope for pre-UAT stabilization)
