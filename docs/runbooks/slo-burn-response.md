---
title: SLO Burn Response Runbook
description: A template for validating an error-budget burn finding and routing a governed response.
---

# SLO Burn Response Runbook

Use this template when a workload SLO emits `slo.error_budget_burn`.

## Procedure

1. Verify the SLO definition, metric source, freshness, and evaluated windows.
2. Confirm short- and long-window thresholds and remaining error budget.
3. Correlate the burn with deployments, maintenance, capacity, and open incidents.
4. Open or update the incident and assign severity from measured impact.
5. Run bounded investigation and what-if for any proposed mitigation.
6. Route the typed proposal through risk and approval policy.

## Stop conditions

Stop when samples are stale, the SLI is mis-scoped, missing data was treated as
zero, or rollback and impact bounds are unavailable.

## Evidence

Record SLO version, window values, source timestamp, incident ID, proposal ID,
verdict, and terminal outcome.
