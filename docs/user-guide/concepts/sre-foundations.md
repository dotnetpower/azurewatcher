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
them: the repeatable majority is run by agents on rules, and a human is asked
only for the risky residual.

This page is the map. It lists the SRE functions FDAI covers, what each one
does, and where to read the mechanism in depth.

## The functions FDAI automates

| SRE function | What it does in FDAI | Vertical / owner |
|--------------|----------------------|------------------|
| Monitoring and observability | Ingests resource-change signals, activity-log events, and detector findings; correlates them into incidents | Heimdall, Huginn |
| Incident detection and response | Routes each signal by confidence, decides a verdict, and acts or escalates | trust-router, Forseti |
| Change management | Gates every proposed change against policy-as-code before it ships | Change Safety |
| Capacity and performance | Right-sizes and scales workloads against measured demand | Freyr, Cost Governance |
| Cost and efficiency | Detects spend anomalies and reclaims waste (idle disks, orphan NICs, unused IPs) | Njord, Cost Governance |
| Reliability and disaster recovery | Runs DR drills, database restore exercises, and bounded chaos experiments | Resilience, Loki, Vidar |
| Toil elimination | Resolves the repeatable majority deterministically, with no human in the path | deterministic-first |
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

## Change management

Before a change ships, it is dry-run against policy-as-code, blast-radius
scoped, and either auto-merged or routed to HIL. Actions are delivered as
**remediation PRs**, so review, approval, and rollback are inherited from git.

Example: an IaC PR proposes a public-egress rule -> the risk gate flags it
high-risk -> an approval card reaches you in Teams -> you approve -> the
executor merges the PR and writes the audit entry.

## Capacity, performance, and cost

Capacity and cost are two views of the same signal: is a resource sized to its
demand? FDAI detects over- and under-provisioning, recommends a right-size, and
auto-executes only the low-risk subset (idle disk cleanup, unused public IP
release, orphan NIC removal). Anything that could degrade a live workload is
gated.

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
approvals, shadow drift, overrides) and proposes catalog updates, so the
deterministic layer keeps getting better without a human re-authoring it by
hand.

## Next steps

| To learn about | Read |
|----------------|------|
| Why the repeatable majority never reaches an LLM | [deterministic-first.md](deterministic-first.md) |
| How verdicts become auto vs HIL | [risk-tiers.md](risk-tiers.md) |
| How every action inherits a safety contract | [ontology-driven-automation.md](ontology-driven-automation.md) |
| Which agents run each function and how they self-heal | [agents-and-self-healing.md](agents-and-self-healing.md) |
| The three verticals end to end | [../get-started.md](../get-started.md) |
