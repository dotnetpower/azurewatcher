---
title: Execution Model
---

# Execution Model

How AIOpsPilot decides **whether** and **how** to run an action. This
document is authoritative for the unified RiskGate, the 5-axis
execution-authority matrix, the three executor paths (PR-native / direct
API / PR-manual), the live-blast probe combinator, and the safety
invariants a live change must satisfy.

Consumers of this model:

- ControlLoop and the operator-console coordinator ask the RiskGate
  before dispatching any action.
- Each executor path implements the safety envelope declared by the
  action's ActionType ([action-ontology.md](action-ontology.md)).
- The operator-console surfaces the `resolved_ceiling` so an operator
  can see exactly why the system decided auto / HIL / deny.

> Customer-agnostic: every ceiling default, probe expression, and role
> assignment below is a placeholder. A fork tunes via the override seams
> documented in
> [action-ontology.md § 7](action-ontology.md#7-fork-override-seams).

## 1. What "execute" means here

Until this document, everything AIOpsPilot did was **shadow** - judge
and log, never mutate. Execution means that after all gates pass, the
executor calls the mutation surface (git PR merge, Azure ARM API,
scripted rollback runner) for real. Shadow mode is still the default
for every new action; execution is a promoted state, per-action, gated
on measured evidence and re-checked on every dispatch.

Three real-world execution paths are supported (§5):

- **PR-native** - the change lands as a git PR that a merge policy
  auto-accepts (or a human accepts). Audit + rollback come from git.
- **Direct API** - the executor calls the substrate API directly (Azure
  ARM, kubectl, Redis). Audit lives in the audit log; rollback lives in
  the ActionType's `rollback_contract`.
- **PR-manual** - the change lands as a PR carrying the `hil` label; no
  auto-merge, an approver must accept. Used for high-risk actions where
  automated verification is not enough.

A single ActionType declares which path it uses; a fork overrides per
environment via the ontology overlays.

## 2. Five-axis authority matrix

The RiskGate collapses **five orthogonal axes** into one decision. Every
axis lowers autonomy independently; the final decision is the
**minimum** of what each axis permits. Nothing here ever raises
autonomy - upgrades go through the promotion pipeline
([phase-2-quality-and-t1.md § Promotion](phases/phase-2-quality-and-t1.md#promotion-shadow--enforce)),
not through the RiskGate at dispatch time.

```
authority = min(
  A_tier          # T0 | T1 | T2
  A_ceiling       # ActionType.ceiling_by_tier[tier]
  A_static_blast  # ActionType.blast_radius (declared)
  A_live_blast    # live probe → quiet | active | overloaded (Month 1+)
  A_role          # min_role vs principal role (RBAC)
  A_env           # prod → downgrade per ActionType.prod_downgrade
)
```

Each axis returns one of:

- `enforce_auto` - allowed to execute without HIL.
- `enforce_hil` - allowed to execute, but a human approval is required.
- `shadow_only` - judge and log; no mutation.
- `deny` - do not proceed; the decision is a hard stop.

The final RiskGate output is a **`RiskDecision`** carrying the winning
minimum plus a `resolved_ceiling` breakdown (§8) that names each axis's
contribution so the audit consumer can render the reasoning.

### 2.1 Axis A - Tier

Comes from the trust router.

| Tier | Default posture |
|------|-----------------|
| T0 (deterministic) | `enforce_auto` allowed - the T0 verdict is a policy-as-code pass |
| T1 (lightweight similarity) | Never higher than `enforce_hil` upstream; a fork MAY raise per-ActionType |
| T2 (frontier reasoning) | Never higher than `shadow_only` upstream; a fork MAY raise but only under an explicit Rego policy naming the ActionType (§7.1 of action-ontology) |

### 2.2 Axis B - ActionType ceiling

From `ceiling_by_tier` on the ActionType (see
[action-ontology.md § 2](action-ontology.md#2-schema)).

### 2.3 Axis C - Static blast radius

The `blast_radius` block on the ActionType. Two computation modes:

- `static_enum` - one of `resource | subnet | subscription`. The wider
  the bucket, the lower this axis returns:
  - `resource` → does not lower autonomy on its own.
  - `subnet` → caps at `enforce_hil`.
  - `subscription` → caps at `enforce_hil` and marks the ceiling
    `wide-blast` so downstream analytics flag it.
- `graph_derived` - computed from the inventory graph at dispatch time.
  A value above `max_affected_resources` caps at `enforce_hil`
  regardless of the other axes.

### 2.4 Axis D - Live blast probe (Month 1+)

`ActionType.live_probe_ref` names a probe. The probe returns one of
three levels (§4). The mapping is:

| Probe result | Effect on ceiling |
|--------------|-------------------|
| `quiet` | no change - static ceiling wins |
| `active` | cap at `enforce_hil` (human approves) |
| `overloaded` | cap at `shadow_only` (defer; too risky right now) |

If `live_probe_ref` is unset the axis returns "no opinion" - it does
not lower autonomy on its own.

### 2.5 Axis E - Role (RBAC)

`ActionType.ceiling_by_tier[tier].min_role` vs the calling principal's
resolved role (from
[user-rbac-and-identity.md](user-rbac-and-identity.md)):

- Principal at or above `min_role` → axis returns the tier default.
- Principal below `min_role` → axis returns `deny`.
- BreakGlass principal → axis returns `enforce_hil` (never `_auto`;
  BreakGlass never bypasses HIL, only makes the reviewer eligible).

For rule-fired actions the "principal" is the executor identity
(system MI); its role is fixed at composition time
([composition.py](../../src/aiopspilot/composition.py)).

### 2.6 Axis F - Environment (prod downgrade)

`ActionType.prod_downgrade` names an env-detector reference. When the
detector returns "prod" for the target resource, the axis caps at
`prod_downgrade.mode` (typically `enforce_hil` or `shadow_only`). A
missing `prod_downgrade` block means the axis is inactive for this
ActionType (dev-only actions ship without it).

### 2.7 Combining

Every axis returns one of the four levels above; the RiskGate takes the
**minimum** in the ordering
`enforce_auto > enforce_hil > shadow_only > deny`. `deny` from any
axis is a hard stop; the executor is never called.

## 3. Unified RiskGate

The RiskGate lives in
[`src/aiopspilot/core/risk_gate/`](../../src/aiopspilot/core/risk_gate/)
and is the single decision point for **both** trigger surfaces (rule-
fired and operator-requested; see
[action-ontology.md § 4](action-ontology.md#4-trigger-surfaces)).

Contract:

```python
class RiskGate(Protocol):
    async def evaluate(
        self,
        *,
        action_type: OntologyActionType,
        action: Action,
        trigger_kind: TriggerKind,
        tier: TrustTier,
        principal: Principal,
        env: EnvClassification,
        promotion_state: ActionModeRecord,
    ) -> RiskDecision: ...

@dataclass(frozen=True)
class RiskDecision:
    decision: Literal["auto", "hil", "abstain", "deny"]
    mode: Literal["shadow", "enforce"]
    execution_path: ExecutionPath          # inherited from ActionType, may be forced lower
    resolved_ceiling: ResolvedCeiling      # audit-friendly breakdown (§8)
    hil_queue_id: str | None               # populated when decision == "hil"
```

- `promotion_state` is read from the existing
  [`ActionPromotionRegistry`](../../src/aiopspilot/core/risk_gate/gate.py) -
  a shadow-mode ActionType clamps `mode` to `shadow` regardless of
  what the axes permit.
- `execution_path` is the ActionType default unless an axis
  (typically the role or env axis) forces a downgrade (e.g. a
  compliance-heavy fork forces `pr_manual` for all direct-API
  ActionTypes in prod).
- The RiskGate is called **once per dispatch attempt**. Re-check on
  retry is a fresh dispatch (fresh audit entry).

### 3.1 Interaction with the operator-console verifier

The console's coordinator re-runs the RiskGate on every write-class
tool call ([operator-console.md § 7.2](operator-console.md#72-three-chat-specific-invariants),
invariant 5). The console never bypasses this path; there is no
"trusted narrator shortcut".

### 3.2 Interaction with `ActionPromotionRegistry`

Promotion is orthogonal to the RiskGate:

- `ActionPromotionRegistry.mode_of(action_type)` decides whether the
  ActionType is enforce-eligible at all.
- The RiskGate takes that as an upper bound and combines it with the 5
  axes. A promoted ActionType may still be gated to `hil` by the axes;
  the promotion state does not force `auto`.

## 4. Live blast probe

Static `blast_radius` says "this ActionType could affect up to a
subnet"; live probes say "this specific resource has zero traffic in
the last 5 minutes, so the affect is nil". Combining static + live is
the mechanism behind the intuition that a running NSG rule change is
low-impact when nothing calls it.

### 4.1 Probe declaration

Probes live under [`rule-catalog/probes/`](../../rule-catalog/probes/):

```yaml
schema_version: "1.0.0"
id: vm_traffic_last_5m
description: "Return quiet/active/overloaded based on VM network throughput over the last 5 minutes."
adapter_ref: probe-adapters/azure-monitor       # DI seam id
kql: |
  AzureMetrics
  | where ResourceId == '{{ target_ref }}'
  | where MetricName == 'Network In Total'
  | where TimeGenerated > ago(5m)
  | summarize p = percentile(Total, 95)
interpretation:
  quiet:      p < 1000000            # <1 MB/5min
  active:     p < 100000000          # <100 MB/5min
  overloaded: p >= 100000000
timeout_seconds: 5
cache_ttl_seconds: 60
```

### 4.2 Runtime shape

The RiskGate calls the probe **only** when:

- `ActionType.live_probe_ref` is set.
- The other axes have not already forced `shadow_only` or `deny`
  (probe cost is only paid when it can actually change the decision).
- The probe cache has no fresh answer for the target.

Probe failure (timeout, adapter error) defaults to `active` - the
safer interpretation. A repeated failure across a rolling window
triggers a `probe.degraded` audit entry so the operator can inspect;
it does not fail-close the entire loop.

### 4.3 Probe adapter seam

```python
class LiveBlastProbe(Protocol):
    async def measure(
        self,
        *,
        probe_id: str,
        target_ref: str,
        deadline_seconds: float,
    ) -> ProbeResult: ...
```

Upstream Day-1 ships the fake `NoOpBlastProbe` (returns "no opinion");
Month-1 adds `AzureMonitorBlastProbe`. A fork may bind any adapter that
implements the Protocol.

## 5. Executor paths

Three paths cover every action; the ActionType names which one and the
RiskGate may downgrade (never upgrade) to `pr_manual`.

### 5.1 PR-native (`pr_native`)

- Executor builds a PR via
  [`GitOpsPrAdapter`](../../src/aiopspilot/delivery/gitops_pr/adapter.py).
- On `auto` decision, the PR carries no `hil` label and the branch's
  auto-merge policy accepts.
- On `hil` decision, the PR carries the `hil` label and an approver
  merges via the console.
- Audit + rollback lean on git: revert commit is the rollback path.

Best for: configuration changes, IaC patches, catalog updates,
governance changes.

### 5.2 Direct API (`direct_api`)

- Executor calls the substrate API directly (Azure ARM, kubectl, Redis
  via the corresponding delivery adapter under `src/aiopspilot/delivery/`).
- On `auto` decision, the call proceeds without HIL; the ActionType's
  `stop_conditions` and `preconditions` are enforced by the executor
  before and during the call.
- On `hil` decision, the executor enqueues a HIL item (identical to
  the PR-manual queue but with `mutation_target=direct` in the item);
  an approver accepts via the console; the executor then dispatches.
- Rollback comes from the ActionType's `rollback_contract`
  (`scripted`, `pitr`, `snapshot_restore`).
- **Idempotency invariant** - every direct-API call uses the action's
  stable idempotency key (existing invariant in
  [coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md));
  a retried call MUST NOT double-apply.

Best for: ops actions where latency matters (restart, scale, cache
flush).

### 5.3 PR-manual (`pr_manual`)

- Same as PR-native but the auto-merge policy is disabled for this
  PR (label `hil` + explicit `merge-not-eligible`).
- Human review is required regardless of the axes; even
  `enforce_auto` on every axis still lands as a manual-merge PR.
- Used for very high-risk actions or compliance-heavy environments
  where every mutation MUST be reviewable diff regardless of
  automation.

Best for: irreversible changes with a scripted rollback, governance
changes that a fork wants a second pair of eyes on regardless of
automation.

### 5.4 Executor selection at dispatch

```
requested_path = ActionType.execution_path
forced_path = RiskGate.resolved_ceiling.forced_execution_path  # optional axis output
final_path = strictest(requested_path, forced_path)
                # strict order: pr_manual > pr_native > direct_api
```

A fork can force every dispatch in prod to `pr_manual` via the env
axis. The upstream never forces from below (never lifts `pr_manual`
to `direct_api` for speed).

## 6. Safety invariants (unchanged + one extension)

Every executed action already carries the four autonomy invariants
from
[coding-conventions.instructions.md § Safety](../../.github/instructions/coding-conventions.instructions.md#safety)
(stop-condition, rollback, blast-radius limit, audit). This document
adds one:

5. **Every dispatch writes its `resolved_ceiling`.** The audit entry
   MUST carry the full 5-axis breakdown that produced the decision, so
   a future overlay change never breaks the reproducibility of a past
   decision.

The other invariants apply exactly as before - no chat-specific
carve-outs, no direct-API relaxation.

### 6.1 Interaction with the operator-console invariants

The chat-specific invariants ([operator-console.md § 7.2](operator-console.md#72-three-chat-specific-invariants))
are additive:

- **Chat invariant 5 (verifier re-check)** = "run the RiskGate on
  every write-class tool call". This document is the definition of
  that RiskGate; the console just calls it.
- **Chat invariant 6 (no self-approval)** = the RiskGate's role axis
  (Axis E) refuses `approve_hil` when the caller's Entra `oid`
  matches the requester recorded on the queued item.
- **Chat invariant 7 (BreakGlass time-boxed)** = Axis E's BreakGlass
  behaviour (§2.5): BreakGlass raises the eligible role for approval
  but never bypasses HIL.

## 7. Determinism + auditability

- Given the same 5-axis inputs, the RiskGate returns the same
  `RiskDecision`. Any stochastic component (a probe that queries a
  moving window) is bounded by `cache_ttl_seconds` on the probe so a
  replay within the TTL yields the identical decision.
- The `resolved_ceiling` block is a full self-explanation of the
  decision - a future overlay change never invalidates a past audit
  entry, because the ceiling that was in effect at dispatch time is
  the record of truth.

## 8. `resolved_ceiling` audit block

Every dispatch writes:

```json
{
  "resolved_ceiling": {
    "tier": "T0",
    "action_type_id": "ops.restart-service",
    "axes": {
      "tier":           {"level": "enforce_auto", "reason": "T0 verdict on shadow-promoted ActionType"},
      "ceiling":        {"level": "enforce_hil",  "reason": "ceiling_by_tier.t0.max_autonomy"},
      "static_blast":   {"level": "enforce_auto", "reason": "static_bucket=resource"},
      "live_blast":     {"level": "enforce_hil",  "reason": "probe=vm_traffic_last_5m returned active", "probe_result": "active"},
      "role":           {"level": "enforce_hil",  "reason": "principal=contributor >= min_role=contributor"},
      "env":            {"level": "enforce_auto", "reason": "not-prod"}
    },
    "winning_axis": "ceiling",
    "final_level":  "enforce_hil",
    "final_path":   "direct_api",
    "overlay_layers_applied": ["upstream", "rego"]
  }
}
```

## 9. Phased rollout

The execution model is a data + policy change; it does not require a
tier upgrade of any subsystem. Rollout matches the ActionType
migration in [action-ontology.md § 10](action-ontology.md#10-migration-plan).

### Day 1

- Schema extension only. Loader learns the new fields; every existing
  ActionType validates. The RiskGate keeps behaving as it does today
  (shadow-only) because `promotion_state` is shadow for every entry.
- **Exit gate**: property tests over the 5-axis min-combination; every
  existing shipped rule still produces the same shadow-only outcome
  it did before the change.

### Week 1

- Ontology backfill lands (see action-ontology.md § 10 step 2).
- ControlLoop starts routing through the unified RiskGate on every
  dispatch (was previously a stub); execution stays shadow-only because
  no ActionType has been promoted yet.
- Operator-console pull-direction ships with the argument-schema-
  validated dispatch path (§3.1).
- **Exit gate**: `resolved_ceiling` audit block appears on every
  dispatch; end-to-end test covers rule-fired and operator-fired paths
  reaching the same executor via the same RiskGate.

### Week 2

- First `ops.*` ActionTypes land with `execution_path=direct_api` and
  `ceiling_by_tier.t0.max_autonomy=enforce_auto`. The RiskGate now
  produces `auto` for those in non-prod on a Reader-visible resource.
- **Exit gate**: a Contributor via the console executes
  `ops.restart-service` on a non-prod resource under live-probe fake
  (`quiet`), the executor calls the (mocked) ARM API, the audit entry
  carries the `direct_api` path.

### Month 1

- Real `AzureMonitorBlastProbe` binds; live probes go live on the
  ActionTypes that opt in.
- `governance.override-ceiling` lands so an Owner can time-box a
  ceiling downgrade from the console (§7.4 of action-ontology).
- **Exit gate**: at least one live probe reduces autonomy at least
  once in production shadow measurement; the audit entry shows
  `winning_axis=live_blast` on that dispatch.

## 10. Testability

- **5-axis matrix** - table-driven property tests over every
  (tier × ceiling × static_blast × live_blast × role × env) combination
  that has a determinate result; assert `min()` semantics.
- **Overlay precedence + resolved_ceiling** - fixture with all four
  overlay layers active on the same axis; assert the higher-precedence
  layer wins and its name appears under `overlay_layers_applied`.
- **Live-probe fake** - `NoOpBlastProbe` returns each of `quiet /
  active / overloaded`; RiskGate output changes as expected.
- **Executor path selection** - table-driven: ActionType.default vs
  forced_path; strict-order winner asserted.
- **Direct-API idempotency** - the executor's dispatch is called
  twice with the same idempotency key; the substrate adapter records
  exactly one mutation.
- **PR-native + PR-manual auto-merge policy** - contract tests over
  the label sets the adapter emits; the label matrix is asserted.
- **RiskDecision cannot upgrade authority** - property test:
  `promotion_state=shadow` on the ActionType → RiskDecision.mode is
  always `shadow` regardless of every other axis.

## 11. Failure modes

- **Probe timeout / error** → default `active` (§4.2); log
  `probe.degraded`; do not fail-close.
- **Overlay load error** (Rego syntax error, missing file overlay
  target) → the loader falls back to upstream defaults and writes
  `overlay.load_failed` audit; the RiskGate marks
  `overlay_layers_applied` accordingly. It does not silently pretend
  the overlay was applied.
- **Executor path unreachable** (direct_api adapter down) → fall back
  to `pr_manual` for that dispatch; write `executor.path.degraded`;
  the operator sees the fallback in the resolved_ceiling on the
  audit entry.
- **RiskGate itself unavailable** (should not happen - it is a pure
  function of its inputs) → fail-close: no dispatch, `deny` audit,
  page the operational lane.

## 12. Related docs

- [action-ontology.md](action-ontology.md) - the ActionType schema this
  document consumes and the override seams a fork uses to tune the
  matrix.
- [operator-console.md](operator-console.md) - the RiskGate is the
  verifier the console's chat invariants require on every write-class
  tool call.
- [phase-2-quality-and-t1.md](phases/phase-2-quality-and-t1.md) - the
  promotion pipeline that flips an ActionType from shadow to
  enforce.
- [risk-classification.md](risk-classification.md) - the initial
  auto / HIL / deny rule table this axis matrix extends.
- [security-and-identity.md](security-and-identity.md) - the four
  autonomy invariants and the executor identity contract.
- [architecture.instructions.md](../../.github/instructions/architecture.instructions.md) -
  trust routing, verifier authority.
