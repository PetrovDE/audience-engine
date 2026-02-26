# Contributing Guide

## Prerequisites

- Python 3.11+
- Docker (for local infra flows)
- PowerShell or shell environment supported by your platform

## Setup

```bash
pip install -r requirements.txt
```

Optional local infra:

```bash
make dev-up
```

## Development Workflow

1. Create a feature branch from `main`.
2. Keep changes scoped and include docs updates when behavior or structure changes.
3. Add or update tests in `tests/unit` and/or `tests/integration`.
4. Run local checks before opening a PR:

```bash
ruff check .
pytest -q tests/unit
pytest -q tests/integration
```

## Pull Request Expectations

- Explain problem, solution, and test evidence.
- Highlight any governance/version contract changes (`fs_version`, `emb_version`, `policy_version`).
- Keep backward-incompatible changes explicit.

## Commit and Review Guidance

- Prefer small, reviewable commits with descriptive messages.
- Do not include secrets, API keys, or sensitive datasets.
- Preserve Architecture V3 constraints:
  - No PII in embeddings or logs.
  - Policy engine remains mandatory before export in production paths.
