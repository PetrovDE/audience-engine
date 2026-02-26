# Audience Engine v0.1.0 (Draft)

## Release Tag

`v0.1.0`

## Summary

Initial public baseline for Audience Engine with:
- Architecture and governance documentation baseline.
- Minimal vertical slice pipeline from synthetic data to approved audience export.
- Retrieval API with health and retrieval endpoints.
- Qdrant blue/green alias workflow support in minimal slice.
- Policy gate integration and reject reason tracking.
- Repository governance/community/release scaffolding for open-source readiness.

## Highlights

- Added release/community documentation:
  - `SECURITY.md`
  - `CONTRIBUTING.md`
  - `CODE_OF_CONDUCT.md`
  - `RELEASE_CHECKLIST.md`
- Added CI workflow:
  - lint (`ruff`)
  - unit tests (`pytest tests/unit`)
  - integration smoke tests (`pytest tests/integration`)
- Added initial automated tests for policy evaluation and retrieval API smoke flow.
- Updated repository manifest/build plan documentation for current project state.

## Known Limitations

- Integration smoke tests are API-level and do not spin up full external services.
- Production deployment hardening and scale verification remain under M5 focus.

## Upgrade/Adoption Notes

- Install dependencies with `pip install -r requirements.txt`.
- Use `make dev-up` for local infrastructure where required.
- Run `python -m pipelines.minimal_slice.run_flow` for end-to-end minimal slice execution.

## Acknowledgements

Thanks to all contributors validating architecture, governance, and minimal slice execution paths.
