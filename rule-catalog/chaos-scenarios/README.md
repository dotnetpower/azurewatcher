# `rule-catalog/chaos-scenarios/`

Catalog-as-code for FDAI fault-injection scenarios.

Data-only YAML tree. Loader + validator live in
[`src/fdai/core/chaos/scenario_catalog.py`](../../src/fdai/core/chaos/scenario_catalog.py).
Design memo:
[`docs/internals/sre-scenario-library-scaling.md`](../../docs/internals/sre-scenario-library-scaling.md).

## Layout

```
chaos-scenarios/
├── schema/                       # JSON Schema for one scenario YAML
│   └── chaos-scenario.schema.json
├── collected/                    # inbound; NOT loaded by default
│   ├── azure-chaos-studio/
│   ├── aws-fis/
│   ├── chaos-mesh/
│   ├── litmus/
│   ├── postmortems/
│   ├── synthesized/              # deterministic combinator output
│   └── gpu/                      # GPU-domain scenarios (usually shadow-only)
├── promoted/                     # gate passed; loaded at startup
├── chaos-scenarios-custom/       # fork-only additions
└── chaos-scenarios-overrides/    # fork-only parameter overrides
```

## Scenario shape

Every YAML file MUST validate against
[`schema/chaos-scenario.schema.json`](schema/chaos-scenario.schema.json).

Minimum example:

```yaml
id: chaos.aks.pod-kill-mild
version: 1
provenance:
  source: chaos-mesh
  synthesis_method: collected
category: compute
target_type: pod
fault_family: stop
intensity: mild
duration_seconds: 360
expected_signal: pod_restart      # must be in core/detection/signals.py
injector: chaos-mesh:PodChaos
blast_radius_cap: 1
rollback_note: "ReplicaSet reschedules the killed pod."
gates:
  shadow_status: pending
  enforce_status: null
requires_hardware: false
```

## Rules

- **Signals**: `expected_signal` MUST match a registered `SIGNAL_*` in
  [`src/fdai/core/detection/signals.py`](../../src/fdai/core/detection/signals.py).
  The loader rejects unknown signals.
- **Injectors**: `injector: needs-injector` is allowed only in `collected/`;
  scenarios with that value cannot land in `promoted/`.
- **Hardware gate**: `requires_hardware: true` scenarios MAY sit indefinitely
  with `enforce_status: pending`; they are still loadable and shadow-testable.
- **Fork boundary**: upstream ships `collected/` + `promoted/` only. Forks
  add or override in `chaos-scenarios-custom/` and `chaos-scenarios-overrides/`
  (fork-only paths). Upstream MUST NOT touch either.
- **No customer values**: scenarios stay CSP-neutral and customer-agnostic.
  `target_selector` is an opaque `<type>:<name>` handle, never a real
  resource name.

## Compiled artifact

The loader also builds a per-`expected_signal` inverted index for O(1)
"which scenarios explain this incident?" lookup at run time
(see `docs/internals/sre-scenario-library-scaling.md` "Symptom index").
The compiled artifact is regenerated on catalog load and never checked in.
