---
title: Triage and Investigation
description: How FDAI gathers bounded cross-resource evidence and produces an auditable investigation report.
---

# Triage and Investigation

Triage establishes ownership, impact, and urgency. Investigation then gathers
the smallest evidence set that can explain the incident without turning a read
operation into a hidden mutation path.

## Investigation contract

An investigation request names the incident, target resources, time range, and
latency budget. Resource analyzers read provider evidence and return structured
findings. The coordinator builds a timeline, correlations, an optional
root-cause hypothesis, and prioritized recommendations.

The report is read-only. A recommendation naming a remediation is still only a
proposal and must re-enter the typed action pipeline.

## Bounded evidence gathering

- **Resource scope** limits which resources an analyzer may inspect.
- **Time range** prevents an unbounded history query.
- **Latency budget** records whether the investigation completed in time.
- **Provider failures** become unavailable evidence, not invented facts.
- **Priorities** rank recommendations as P1, P2, or P3 without granting
  execution authority.

## Triage workflow

1. Confirm incident severity, owner, affected resources, and user impact.
2. Check whether telemetry and inventory are fresh enough to investigate.
3. Run analyzers only for the declared resource types.
4. Build the ordered timeline before asserting causality.
5. Separate correlated observations from grounded root-cause hypotheses.
6. Route actionable recommendations to an incident response plan or normal
   action proposal.

## Read the report

| Section | Question it answers |
|---------|---------------------|
| Findings | What did each resource analyzer observe? |
| Timeline | In what order did changes and symptoms occur? |
| Correlations | Which observations move together? |
| RCA hypothesis | What cause is supported by cited evidence? |
| Recommendations | What should be inspected, simulated, or proposed next? |
| Budget result | Did evidence gathering finish within its declared limit? |

## Failure behavior

A wedged analyzer is bounded and produces a no-action result. An exception is
recorded as unavailable evidence rather than crashing the response and losing
the audit trail. Cancellation still aborts the investigation cleanly.

## Next steps

| To learn about | Read |
|----------------|------|
| How the incident record changes | [Incident management](incident-management.md) |
| How cited hypotheses are gated | [Root-cause analysis](root-cause-analysis.md) |
| How a recommendation becomes a proposal | [Response plans and mitigation](response-plans-and-mitigation.md) |
| How to inspect supporting records | [Read the audit log](../guides/read-audit-log.md) |
