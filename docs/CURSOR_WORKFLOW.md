# Cursor Workflow (Bootstrap)

## Required Read Order Per Task
1. `docs/REPO_MANIFEST.md`
2. `docs/ARCHITECTURE_V3.md`
3. `docs/INDEX.md`
4. `docs/DOCS_BUNDLE.md`
5. `docs/BUILD_PLAN.md`
6. Relevant rule files under `.cursor/rules/`

## Working Protocol
- Use milestone-first execution (M0, M1, ...).
- Before large edits, publish a Change Plan listing files to create/modify.
- Read only files relevant to the current task.
- Keep updates scoped, explicit, and reversible.

## Change Plan Template
- Goal: one sentence objective.
- Files: list of files to create/modify.
- Impact: architecture/governance/workflow impact summary.
- Validation: checks to run after edits.

## Governance and Versioning Checklist
When changing features, embeddings, policies, or index behavior:
- Bump required version (`fs_version`, `emb_version`, `policy_version`) as applicable.
- Add changelog note for registry or policy updates.
- Confirm no PII enters embeddings or logs.
- Confirm allowlist-only embedding inputs.
- Confirm audience run lineage includes all required versions and index alias/version.

## Policy Gate Invariant
- No production export is allowed without Policy Engine enforcement.
- Rejections must emit standardized reason codes.
- Campaign/audience runs must persist audit records.

## Documentation Hygiene
- Keep `docs/INDEX.md` as the canonical TOC for all docs.
- Update architecture docs when boundaries or invariants change.
- Update manifest when repo structure changes.
- Update build plan when milestone scope or order changes.
- Keep docs implementation-agnostic unless a milestone explicitly requires operational detail.
