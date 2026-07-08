# ActionType custom additions (fork-only)

Drop folder for **brand-new** ActionTypes authored by a downstream
fork. This is the "separate catalog root" seam described in
[../../docs/roadmap/downstream-fork-seam-recipes.md § 5.12](../../docs/roadmap/downstream-fork-seam-recipes.md)
and is distinct from the overlay layer in
[../action-types-overrides/](../action-types-overrides/README.md):

| Folder | Purpose | Loader semantics |
|--------|---------|------------------|
| `../action-types/` | upstream, customer-agnostic ActionTypes | loaded by the composition root |
| `../action-types-overrides/` | fork **tightens an existing** ActionType | deep-merged onto a matching upstream file; an orphan `name` is a fatal error |
| `action-types-custom/` (here) | fork **adds a new** ActionType | loaded as its own catalog root and concatenated; never merged onto upstream |

## Why a separate folder (not an overlay)

The overlay loader rejects an overlay whose `name` has no upstream
match, so a typo cannot silently introduce a phantom ActionType. That
same rule means a fork **cannot** create a new ActionType through the
overlay directory. New ActionTypes therefore come from a second
`load_action_type_catalog(...)` call over this root, whose result is
concatenated with the upstream catalog:

```python
from pathlib import Path

from fdai.rule_catalog.schema.action_type import load_action_type_catalog

upstream = load_action_type_catalog(
    Path("rule-catalog/action-types"),
    schema_registry=registry,
    probes_root=Path("rule-catalog/probes"),
)
custom = load_action_type_catalog(
    Path("fork/action-types-custom"),  # a fork points this at its own tree
    schema_registry=registry,
    probes_root=None,                  # a fork MAY ship its own probes
)
action_types = upstream + custom
```

A duplicate `name` across the two roots is a hard load error, so a fork
cannot shadow an upstream ActionType by re-declaring it here - that is
what the overlay layer is for.

## Upstream ships this directory empty

Per the fork model in
[../../.github/instructions/generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md),
customer-specific ActionTypes live in a downstream fork, never in this
repository. Upstream keeps only the example template below so a fork has
a copy-paste starting point.

## The `.yaml.example` template

[`ops.example-custom-op.yaml.example`](ops.example-custom-op.yaml.example)
is a complete, schema-valid ActionType with the `.example` suffix so the
loader glob (`*.yaml`) skips it - the upstream catalog stays empty of
runnable custom ActionTypes. To adopt it in a fork:

1. Copy the file into the fork's own custom root.
2. Rename it to end in `.yaml` (drop `.example`) and give it a unique
   `name` that does not collide with any upstream ActionType.
3. Keep `default_mode: shadow` and every `ceiling_by_tier` at
   `shadow_only` until a measured shadow window justifies promotion
   (see [../action-types/README.md](../action-types/README.md)).

## Rules

- Every non-example `<name>.yaml` here validates against the same schema
  as [`../action-types/`](../action-types/README.md) and MUST default to
  `shadow` with a measurable `promotion_gate`.
- `name` MUST be unique across upstream **and** this root; a collision is
  a fatal load error.
- Do not use this folder to weaken an existing ActionType - use an
  overlay under [`../action-types-overrides/`](../action-types-overrides/README.md).
- Never commit customer-identifying values (see
  [../../.github/instructions/generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).
