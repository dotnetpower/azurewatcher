# Pantheon Runtime (`fdai.agents`)

Runtime home for the 15 named pantheon agents. Design authority:
[docs/roadmap/agent-pantheon.md](../../../docs/roadmap/agent-pantheon.md).
Wave plan: [agent-pantheon-implementation.md](../../../docs/roadmap/agent-pantheon-implementation.md).

## Layout

| File | Purpose |
|------|---------|
| `base.py` | `Agent` abstract, `AgentSpec` immutable declaration, `Layer` enum, `RateLimits` |
| `pantheon.py` | The 15 `AgentSpec` instances (upstream-locked); `PANTHEON_SPECS`, `PANTHEON_NAMES`, `HARD_DEPENDENCY_AGENTS`, `LLM_HOT_PATH_ALLOWLIST` |
| `registry.py` | `PantheonRegistry` - single-writer invariant, publish authorization, owner lookup |
| `topics.py` | Topic naming (`object.<kebab>`), partition-key strategy, owned-topic set |
| `bus.py` | `InMemoryBus` - sync-dispatch pub/sub used by tests and single-process runs; `PantheonBus` Protocol - the bus contract agents depend on |
| `bus_bridge.py` | `EventBusBridge` - binds the pantheon to a real `EventBus` provider (Kafka / Event Hubs) with per-agent consumer groups |
| `runtime.py` | `PantheonRuntime` - composition-root wiring: instantiates + binds all 15 agents, registers subscriptions, routes ingress to Huginn, exposes `run()` / `stop()` |
| `adapters.py` | In-memory adapters for audit chain, state store, GitHub Issues, ChatOps admin channel |
| `factory.py` | `instantiate_pantheon()` - build all 15 concrete instances |
| `workflows.py` | The 10 cross-agent `WorkflowSpec` catalog |
| `kpi.py` | `KpiCollector`, `PromotionGate`, `PromotionGateThreshold` |
| `odin.py` `thor.py` `forseti.py` ... | One file per pantheon agent (15 total). Each subclasses `Agent`, binds its `AgentSpec`, and implements `on_typed_message` / helper methods per its wave-plan mandate |

## Testing

- `tests/agents/test_registry.py` - single-writer invariant, publish authorization, canonical set
- `tests/agents/test_topics.py` - topic naming + partition keys
- `tests/agents/test_stubs.py` - all 15 stubs instantiate + honest abstain
- `tests/agents/test_ontology_alignment.py` - YAML `Agent` object type <-> Python pantheon parity
- `tests/agents/test_wave2_governance.py` - Saga chain + Issue dedup, Mimir promotion, Muninn store, Norns fingerprint counter
- `tests/agents/test_wave3_pipeline.py` - Huginn / Heimdall / Forseti / Var / Vidar / Thor + end-to-end verdict loop
- `tests/agents/test_wave4_interface.py` - Bragi routing + scoring, Odin arbitration + priority table
- `tests/agents/test_wave5_specialists.py` - Njord anomaly, Freyr forecast, Loki blast-radius
- `tests/agents/test_wave6_handoff_security.py` - Handoff -> Issue -> Norns -> Mimir; Security -> admin card dedup + rate limit
- `tests/agents/test_wave7_workflows.py` - 10 workflow catalog + smoke traces
- `tests/agents/test_wave8_kpi_degradation.py` - KPI collector, promotion gate, degradation drills

Run just the pantheon suite: `pytest tests/agents/ -q`.

## Fork integration seams

Every in-memory adapter in `adapters.py` sits behind an implicit contract that
fork adapters implement to point at the real backend:

| In-memory adapter | Fork replaces with |
|-------------------|--------------------|
| `InMemoryAuditChain` | Postgres append-only table, or event-sourced Kafka partition |
| `InMemoryStateStore` | Postgres + pgvector for RAG |
| `InMemoryGithubIssueAdapter` | GitHub REST API with the fork's App credentials |
| `InMemoryAdminChannel` | Teams Bot Framework Adaptive Card delivery |
| `InMemoryBus` | Kafka client wrapped on Event Hubs `:9093` |

None of the in-memory adapters read customer identifiers; fork adapters live
in the downstream fork per the
[generic-scope](../../../.github/instructions/generic-scope.instructions.md) rule.

## Invariants enforced in code

- Single-writer per topic (`PantheonRegistry.assert_can_publish`)
- Judge != executor (Forseti and Thor are distinct classes with disjoint owned types)
- Hard dependency: Saga + Vidar; without them `Thor.dispatch_verdict` demotes new mutations to shadow
- Hot-path LLM allowlist is `{Bragi, Forseti, Norns}` - other classes must not import an LLM client synchronously
- Blast-radius: `PantheonRuntime` forces Thor to shadow (`enforce=False` default); a crashed bridge consumer is isolated (siblings survive) and a pantheon crash never cancels the P1 control plane
- Bounded memory: Huginn dedup is an LRU capped at `dedup_capacity`; DLQ-write failures are counted, not fatal (`EventBusBridge._safe_dead_letter`)
- Fingerprint dedup via `saga.compute_fingerprint` + `Saga.escalate_to_github_issue`
- Blast-radius cap via `Loki.propose_experiment`
- HIL quorum via `Var.decide` (self-approval raises)
