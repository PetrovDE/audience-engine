# Entity Lifecycle (Control Plane v1)

## Purpose
Define lifecycle states and transition rules for versioned control-plane entities.

## Lifecycle Semantics
- `validation`: Technical/governance checks pass; artifact is still not the production active version.
- `activation`: Version is promoted to active use for new runs.
- `deprecation`: Version remains readable/auditable but should not be selected for new runs.
- `rollback`: Active pointer is moved back to a previously validated/active version; old artifact remains immutable.

## Common Versioned-State Model
Default state model for `FeatureSetVersion`, `ModelVersion`, `EmbeddingModelVersion`, `PolicyVersion`, `AudienceDefinitionVersion`:

`draft -> validated -> active -> deprecated -> retired`

Allowed recovery transitions:
- `validated -> draft` (fix and revalidate)
- `active -> deprecated` (planned replacement or risk)
- `deprecated -> active` (limited rollback/reactivation when still compatible)
- `deprecated -> retired` (final removal from selection)

Not allowed:
- Direct `draft -> active`
- Mutating an existing immutable version payload after `validated`

## Entity-Specific State Matrix
| Entity type | States | Allowed transitions |
| --- | --- | --- |
| `FeatureSetVersion` | `draft`, `validated`, `active`, `deprecated`, `retired` | Common model |
| `ModelVersion` | `draft`, `validated`, `active`, `deprecated`, `retired` | Common model |
| `EmbeddingModelVersion` | `draft`, `validated`, `active`, `deprecated`, `retired` | Common model + must pass embedding contract checks |
| `PolicyVersion` | `draft`, `validated`, `active`, `deprecated`, `retired` | Common model + reason-code binding validation |
| `AudienceDefinitionVersion` | `draft`, `validated`, `active`, `deprecated`, `retired` | Common model + compatibility checks for fs/emb/policy refs |
| `IndexGeneration` | `built`, `validated`, `promoted`, `rolled_back`, `failed` | `built->validated->promoted`, `promoted->rolled_back`, failure edges from any stage |
| `IndexAlias` pointer | runtime pointer state | Moves only through audited `promote_alias` / `rollback_alias` actions |

## Index Promotion and Rollback Semantics
`IndexGeneration` is operationally different from immutable metadata versions:

1. Build creates a new concrete generation (`built`).
2. Validate confirms count/query/vector integrity (`validated`).
3. Promote atomically repoints alias and marks generation `promoted`.
4. Rollback atomically repoints alias to previous generation and marks current generation `rolled_back`.
5. All mutate actions must write lifecycle audit with actor identity and outcome.

## Activation Rules by Entity
| Entity | Activation gate |
| --- | --- |
| `FeatureSetVersion` | Contract validation + no-PII/allowlist governance pass |
| `ModelVersion` / `EmbeddingModelVersion` | Runtime compatibility + performance/readiness evidence |
| `PolicyVersion` | Rule validation + required data-source contract checks |
| `AudienceDefinitionVersion` | Compatibility with active fs/emb/policy versions |
| `IndexGeneration` | Must be `validated` before promotion |

## Implemented vs Target-State Notes
Implemented as of 2026-04-10:
- Index lifecycle states (`built`, `validated`, `promoted`, `rolled_back`, `failed`) and audited transitions are operational.
- Policy version selection and compatibility checks exist in control-plane runtime flow.

Target-state:
- First-class persisted lifecycle states for all versioned entities (feature/model/embedding/policy/audience definition).
- Consistent rollback tooling across metadata entities, not only index alias operations.
