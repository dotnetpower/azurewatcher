---
title: SRE foundations
description: The core SRE functions FDAI automates, and how each maps to the control loop, the agents, and the three verticals.
sidebar:
  order: 1
---

# SRE foundations

FDAI is an autonomous take on **Site Reliability Engineering (SRE)**. The SRE
discipline defines a set of recurring functions - watch the system, catch
regressions, ship changes safely, plan capacity, control cost, prepare for
disaster, and eliminate toil. FDAI keeps those functions but changes who runs
them: repeatable cases are candidates for rule-driven handling, and people stay
in the loop for novel, high-risk, or insufficiently grounded cases. Actual
autonomous coverage is measured after shadow evaluation and promotion.

This page is the map. It lists the SRE functions FDAI covers, what each one
does, and where to read the mechanism in depth.

## The functions FDAI automates

| SRE function | What it does in FDAI | Vertical / owner |
|--------------|----------------------|------------------|
| Monitoring and observability | Ingests resource-change signals, activity-log events, and detector findings; correlates them into incidents | Heimdall, Huginn |
| Incident detection and response | Routes each signal by confidence, decides a verdict, and acts or escalates | trust-router, Forseti |
| Change management | Gates every proposed change against policy-as-code before it ships | Change Safety |
| Capacity and performance | Detects sizing gaps and proposes or runs promoted scaling actions against measured demand | Freyr, Cost Governance |
| Cost and efficiency | Detects spend anomalies and evaluates promoted waste-removal candidates | Njord, Cost Governance |
| Reliability and disaster recovery | Plans and runs promoted DR drills, restore exercises, and bounded chaos experiments | Resilience, Loki, Vidar |
| Toil elimination | Moves proven repeatable cases from manual handling to deterministic rules | deterministic-first |
| Postmortem and learning | Records an append-only audit entry for every action and proposes catalog updates from operating signals | Saga, Norns |

## Monitoring and observability

FDAI is event-driven, not a polling dashboard. Resource changes, activity-log
events, and anomaly or forecast findings arrive on the event bus. The sensing
agents normalize, deduplicate, and correlate them into incidents so a single
root event is not counted as ten symptoms.

Example: five alerts fire from one failed deployment -> the collector correlates
them on a shared resource key -> one incident enters the loop, not five.

## Incident detection and response

Every correlated event is scored by the **trust router**, which picks the
lowest tier competent to decide it (see
[risk-tiers.md](risk-tiers.md)). Deterministic cases resolve at T0 with no model
call; ambiguous cases escalate. Detection stays deterministic-first: an anomaly
or a prediction raises a *finding* that the risk gate governs - it never
auto-acts on its own.

## A finding is not an action

An anomaly, forecast, correlation, or root-cause result is evidence. It enters
the same trust router and risk gate as any other event. It becomes an executable
action only when a valid `ActionType` supplies the safety contract and every
verification, scope, lock, and approval requirement passes.

Example: a forecast predicts capacity exhaustion -> Freyr emits a finding ->
the router selects a tier -> the risk gate evaluates the proposed scaling
action -> shadow, HIL, or promoted auto behavior follows. The prediction itself
never scales the workload.

## Change management

Before a change ships, it is dry-run against policy-as-code, blast-radius
scoped, and either prepared for a configured PR-native policy or routed to HIL. Actions are delivered as
**remediation PRs**, so review, approval, and rollback are inherited from git.

Example: an IaC PR proposes a public-egress rule -> the risk gate flags it
high-risk -> an approval card reaches you in Teams -> you approve -> the
PR-native merge policy or authorized approver completes delivery -> FDAI writes
the audit entry.

## Capacity, performance, and cost

Capacity and cost are two views of the same signal: is a resource sized to its
demand? FDAI detects over- and under-provisioning and recommends a right-size.
Low-risk candidates such as unattached public IP release must still collect
shadow evidence and be promoted independently before auto execution. Anything
that could degrade a live workload remains gated.

## Reliability and disaster recovery

Reliability work is proactive here. Scheduled DR drills, database restore
exercises, and blast-radius-bounded chaos experiments run on a cadence. Cadence,
scope, and proof stay separated: the scheduler owns cadence, the risk gate owns
scope, and the audit log owns proof.

## Toil elimination

The whole point of the deterministic-first design is to remove toil. Because the
repeatable majority is decided by rules, operators stop hand-approving the same
drift, cost regression, or policy violation every week. The human is reserved
for the novel and the high-risk (see
[deterministic-first.md](deterministic-first.md)).

## Postmortem and learning

Every terminal decision - including no-ops, rejects, and HIL timeouts - writes
an append-only audit entry. A learning loop watches those signals (HIL
approvals, shadow drift, overrides) and proposes grounded catalog candidates.
It never edits or promotes the catalog directly.

## How SRE improvement is measured

Use paired baseline and treatment windows over the same scenario set. Outcome
metrics include MTTR distribution (mean, median, and p90), auto-resolution rate,
human touchpoints per incident, change lead time, and cost per resolved event.
Guard metrics include change-failure rate, false-positive and false-negative
rates, rollback rate, policy-violation escapes, and audit gaps.

FDAI does not claim an improvement from a higher automation percentage alone.
The result counts only when the outcome improves without regressing the guard
metrics.

## When FDAI itself is unhealthy

The control plane exposes readiness, event lag, dead-letter depth, dependency
health, synthetic-canary results, and audit completeness. A required dependency
failure lowers affected actions to shadow or deny. The executor stops mutation
when the safety contract, inventory freshness, lock, rollback support, or audit
write cannot be guaranteed.

This behavior keeps an observability failure from becoming an autonomy failure.
Operators can still inspect the degraded state and queued work without the
console or notification channel inheriting executor authority.

## Next steps

| To learn about | Read |
|----------------|------|
| Why the repeatable majority never reaches an LLM | [deterministic-first.md](deterministic-first.md) |
| How verdicts become auto vs HIL | [risk-tiers.md](risk-tiers.md) |
| How every action inherits a safety contract | [ontology-driven-automation.md](ontology-driven-automation.md) |
| Which agents run each function and how they self-heal | [agents-and-self-healing.md](agents-and-self-healing.md) |
| The three verticals end to end | [../get-started.md](../get-started.md) |
