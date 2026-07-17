---
title: Incident Triage Runbook
description: A customer-neutral template for confirming incident scope, severity, ownership, and investigation readiness.
---

# Incident Triage Runbook

Use this template when an incident opens or materially changes severity or scope.

## Preconditions

- Confirm the incident ID, correlation keys, current state, and member count.
- Confirm telemetry and inventory freshness; mark unavailable sources explicitly.
- Assign an accountable owner and verify the on-call schedule used.

## Procedure

1. Validate affected resources and remove unrelated members only through an audited correction.
2. Set severity from measured user impact, SLO burn, and bounded scope.
3. Move the incident to `triaging` with the expected current state.
4. Start a time- and resource-bounded investigation.
5. Record evidence links, unknowns, and the next decision deadline.
6. Notify the selected responder and verify durable delivery status.

## Stop conditions

Stop and escalate when identity, ownership, scope, or evidence freshness cannot
be established. Do not lower severity from missing data.

## Evidence

Record transition audit ID, owner, severity basis, member references,
investigation ID, notification result, and next review time.
