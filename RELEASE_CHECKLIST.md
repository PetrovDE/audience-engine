# Release Checklist

## Version

- Target tag: `v0.1.0`
- Release type: initial public baseline

## Pre-Release Validation

- Confirm docs consistency (`README.md`, `docs/REPO_MANIFEST.md`, architecture/governance references).
- Verify `LICENSE` is Apache-2.0.
- Confirm required community/security docs exist:
  - `SECURITY.md`
  - `CONTRIBUTING.md`
  - `CODE_OF_CONDUCT.md`
- CI green on `main`:
  - lint
  - unit tests
  - integration smoke tests

## Functional Checks

- Minimal vertical slice executes in local/dev environment.
- Retrieval API `/healthz` responds with status `ok`.
- Policy gate is enforced before export path.
- Run summary includes version lineage (`fs_version`, `policy_version`, index metadata).

## Governance and Security Checks

- No PII in embedding inputs/logging paths.
- Governance registries are versioned and references resolve correctly.
- No secrets committed in repository content.

## Release Operations

- Draft and review release notes (`RELEASE_NOTES_v0.1.0.md`).
- Create annotated tag `v0.1.0` after final approval.
- Publish GitHub release using approved notes.

## Post-Release

- Verify package/repository metadata renders correctly.
- Track first adopter issues and hotfix candidates.
