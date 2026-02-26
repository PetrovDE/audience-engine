# Repository Manifest (Bootstrap)

## Current Repository Inventory
- `.cursor/rules/00-constitution.mdc`
- `.cursor/rules/01-workflow.mdc`
- `.cursor/rules/10-governance.mdc`
- `.cursor/rules/20-policy-engine.mdc`
- `README.md`
- `LICENSE`

## Docs Added in M0
- `docs/ARCHITECTURE_V3.md`
- `docs/REPO_MANIFEST.md`
- `docs/BUILD_PLAN.md`
- `docs/CURSOR_WORKFLOW.md`

## Intended Top-Level Layout (Planned)
- `docs/` architecture, workflow, governance, runbooks.
- `governance/` versioned registries and policy artifacts.
- `services/` deployable service applications.
- `pipelines/` data, feature, and embedding jobs.
- `infra/` docker-compose, environment templates, deployment assets.
- `tests/` unit, integration, performance, and contract tests.
- `scripts/` operational utilities and local automation.

## Planned Docs (Future)
- `docs/GOVERNANCE.md`
- `docs/POLICY_ENGINE.md`
- `docs/INDEX_LIFECYCLE.md`
- `docs/RUNBOOKS/` operational procedures.

## Manifest Rules
- Update this manifest when top-level structure changes.
- Reference new governed registries and version artifacts as they are introduced.
- Keep this file concise and implementation-agnostic.
