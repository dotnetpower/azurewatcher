---
title: Get Started with AIOpsPilot
description: A five-minute orientation to AIOpsPilot - what it is, when it fits, and where to look next.
---

# Get Started with AIOpsPilot

AIOpsPilot is an autonomous cloud operations control plane. It resolves the
repeatable majority of operational events deterministically with rules, policies,
and typed actions, and reserves LLM inference for the ambiguous residual that
survives the deterministic gate. Every autonomous action is risk-classified, and
anything above the safe threshold pauses for human-in-the-loop (HIL) approval.

The reference implementation targets Azure. The design keeps a cloud-neutral seam
so other CSPs are additive rather than requiring a core rewrite, but no non-Azure
adapter ships today.

## What can you achieve?

AIOpsPilot ships three verticals under one event-driven core. Each loads its own
rules and actions but shares the control loop, observability, audit log, and
risk gate.

### Change Safety

Rule-catalog-driven policy gates on every proposed change. Each candidate is
dry-run against policy-as-code, blast-radius scoped, and either auto-merged or
routed to HIL.

Example: an IaC PR proposes a public-egress NSG rule -> risk gate flags
high-risk -> HIL approval card in Teams -> approver clicks approve -> executor
merges the remediation PR + writes the audit entry.

### Resilience

Scheduled DR drills, database DR exercises, and blast-radius-bounded chaos
experiments. Cadence, scope, and proof stay separated: scheduler owns cadence,
risk gate owns scope, audit log owns proof.

Example: a nightly job finds a PITR gap on a critical database -> agent schedules
a paired restore drill in the exercise window -> restore succeeds against target
RPO/RTO -> audit entry recorded.

### Cost Governance

Anomaly detection on spend, right-sizing recommendations, and auto-execution of
the low-risk subset (idle disk cleanup, unused public IP release, orphan NIC
removal).

Example: cost-anomaly detector fires on cache-tier over-provisioning -> T0 rule
matches -> two-week shadow proves accuracy -> promotion to enforce -> right-size
remediation PR ships with a rollback path.

## How it works

Three tiers, one loop. The trust router picks the lowest tier that can decide
the event; the risk gate decides whether the resulting action auto-executes or
waits for approval.

1. **T0 (deterministic, ~70-80% target coverage)**: policy-as-code decisions
   with a known correct outcome. No model call, no ambiguity.
2. **T1 (lightweight, ~15-20%)**: pattern matching, embedding similarity, and
   small-model classifiers over the audit log's history. Cheap, fast, and
   auditable.
3. **T2 (deep reasoning, ~5-10%)**: frontier models with mixed-model
   cross-check, deterministic verifier, and grounding checks. LLMs generate;
   execution eligibility is granted by verifier, not by the model.

```text
event -> event-ingest -> trust-router -> T0 | T1 | (T2 -> quality-gate)
      -> risk-gate    -> auto | HIL | abstain -> executor -> delivery -> audit
```

Coverage percentages are targets that require a measured baseline before they
can be claimed
([goals-and-metrics](../roadmap/goals-and-metrics.md)).

## When AIOpsPilot fits

AIOpsPilot is a good fit when all of these are true:

```mermaid
flowchart TB
  Q1{Do operators<br/>repeatedly approve or<br/>roll back the same<br/>types of events?}
  Q1 -->|no| N1[Not the fit yet - the<br/>deterministic tier has<br/>nothing repeatable to<br/>automate.]
  Q1 -->|yes| Q2{Is infrastructure<br/>expressed as IaC and<br/>policy-as-code?}
  Q2 -->|no| N2[Not the fit yet - T0<br/>needs machine-readable<br/>rules to run.]
  Q2 -->|yes| Q3{Is a baseline<br/>reproducible for<br/>measuring gains?}
  Q3 -->|no| N3[Build the baseline first<br/>Phase 0 exists precisely<br/>for this.]
  Q3 -->|yes| Q4{Are you on Azure?}
  Q4 -->|no| N4[Adapter is TBD for other<br/>CSPs. Not shipped yet.]
  Q4 -->|yes| OK[AIOpsPilot fits.<br/>Start with Phase 0.]
```

- Operators already spend real time approving or rolling back repeatable
  cloud-configuration events (drift, cost regressions, policy violations).
- Your infrastructure is expressed as IaC and policy-as-code, or you are
  moving that way.
- You have, or can construct, a baseline to measure autonomy gains against.
  AIOpsPilot never claims a multiplier without a paired measurement.
- Your compliance regime tolerates auto-executed low-risk changes provided
  every action has a stop-condition, rollback path, blast-radius limit, and
  audit-log entry.

## When AIOpsPilot doesn't fit (yet)

- **No IaC or no policy-as-code**: the deterministic tier has nothing to run.
- **One-off, non-repeatable incidents**: AIOpsPilot's edge comes from
  resolving the repeatable majority; the residual novel minority stays with
  humans.
- **Non-Azure CSPs**: abstractions are neutral by design, but the Azure
  adapter is the only one shipped.

## Grows with your environment

- **Day 1**: T0 rules run in shadow mode on your events. Every finding writes
  an audit entry so you can see what it would have done.
- **Week 1**: shadow metrics show which actions clear their promotion gate.
  T1 starts reusing patterns from resolved incidents; T2 stays a small share.
- **Month 1**: promoted actions run autonomously with rollback paths. The
  discovery loop begins proposing catalog updates from your own operating
  signals (HIL approvals, shadow drift, overrides).

## Next steps

| To learn about | Read |
|----------------|------|
| Why deterministic first | [concepts/deterministic-first.md](concepts/deterministic-first.md) |
| The three trust tiers in depth | [concepts/risk-tiers.md](concepts/risk-tiers.md) |
| Shadow-mode rollout and promotion | [concepts/shadow-then-enforce.md](concepts/shadow-then-enforce.md) |
| Approving a change on the operator side | [guides/approve-change.md](guides/approve-change.md) |
| Reading the audit log | [guides/read-audit-log.md](guides/read-audit-log.md) |
| Narrowing a rule for one scope | [guides/override-a-rule.md](guides/override-a-rule.md) |
| The full engineering roadmap | [../roadmap/README.md](../roadmap/README.md) |
