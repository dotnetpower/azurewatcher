---
title: Capacity and Performance
description: How FDAI turns measured demand and forecasts into bounded capacity findings and governed scaling proposals.
---

# Capacity and Performance

Capacity work asks whether a resource can meet measured demand without wasting
cost or exhausting a dependency. FDAI combines current utilization, forecast
evidence, minimum floors, dependency checks, and promotion state before it can
propose a scaling action.

## Capacity evidence

- Current utilization and saturation by resource and window.
- Demand trend, forecast horizon, uncertainty, and expected breach time.
- Minimum and maximum capacity plus warm-capacity floors.
- Quota, regional availability, and dependent-resource constraints.
- Workload SLO and error-budget impact.
- Cost estimate and rollback or scale-back path.

Missing or stale telemetry produces unavailable or abstained evidence. It does
not produce a zero-demand assumption.

## Decide without conflicting specialists

Freyr evaluates capacity while Njord evaluates cost. Their advice can conflict,
such as scale up for reliability versus scale down for efficiency. Specialists
remain advisory; Forseti and the risk gate apply the configured precedence and
autonomy ceiling.

## Scaling proposal flow

1. A detector or scheduled evaluation emits a capacity finding.
2. The finding correlates with workload SLO, current changes, and incidents.
3. What-if verifies quota, dependencies, floors, and expected effect.
4. A typed scale proposal carries scope, batch, rate, stop condition, and rollback.
5. Shadow evidence and promotion state determine whether the proposal can reach
   approval or promoted auto behavior.

## Guardrails

Never scale below a declared safety floor, strand a dependency, exceed quota,
or treat a forecast as execution authority. Per-resource locks and bounded
batch changes prevent competing scale actions from racing.

## Next steps

| To learn about | Read |
|----------------|------|
| How forecasts are formed | [Observability, detection, and forecasting](observability-detection-and-forecasting.md) |
| How workload impact is measured | [SLOs and error budgets](slos-and-error-budgets.md) |
| How cost and capacity interact | [Cost Governance](../capabilities/cost-governance.md) |
| How actions are promoted | [Shadow, then enforce](../concepts/shadow-then-enforce.md) |
