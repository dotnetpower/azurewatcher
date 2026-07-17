---
title: Alert Tuning Runbook
description: A template for reducing alert noise and missed detection through measured rule and routing changes.
---

# Alert Tuning Runbook

Use this template when false positives, false negatives, duplicate incidents, or stale routing regress.

## Procedure

1. Freeze a labeled scenario set and current detector, correlation, and routing versions.
2. Measure fire rate, precision, recall, duplicate ratio, cold-start abstentions, and delivery outcomes.
3. Identify whether the defect belongs to baseline, threshold, seasonality, debounce, correlation, or channel routing.
4. Change one configuration axis and rerun the same scenarios in shadow.
5. Confirm no policy-violation escape or guard-metric regression.
6. Review and promote the change independently; retain rollback to the prior version.

## Stop conditions

Do not suppress an alert solely to reduce volume. Stop when labels are
insufficient, the treatment set differs from baseline, or missed incidents rise.
