---
title: On-Call and Escalation
description: How FDAI selects accountable responders, escalates pending decisions, and fails closed when paging integrations are unavailable.
---

# On-Call and Escalation

On-call routing connects an incident to an accountable human without giving a
notification channel execution authority. FDAI resolves the current responder,
applies the configured escalation ladder, and records every timeout, reroute,
approval, and no-op.

> The upstream on-call schedule seam and fail-safe resolver are implemented.
> PagerDuty or Opsgenie adapters and channel-specific direct-message targeting
> remain deployment or fork bindings. Status-page broadcast is deferred.

## Resolve the responder

The resolver reads a time-bounded schedule and returns the principal on shift.
If the schedule is missing, stale, or unavailable, FDAI uses the configured
fail-safe route and records degraded routing. It does not guess an identity.

Approval and execution remain distinct principals. An on-call responder can
review or approve only within RBAC and policy; being on shift does not grant
executor credentials.

## Escalation ladder

An escalation ladder defines levels, wait periods, channels, roles, and stop
conditions. A pending decision can move from primary on-call to secondary,
incident commander, or owner according to scope and severity.

The slower supervisory loop never changes the underlying risk verdict. It can
seek an accountable approver or expire the request, but cannot turn `deny` into
`auto` or approve on behalf of a person.

## Operator checks

1. Confirm schedule freshness, timezone, and handoff boundary.
2. Confirm incident scope and severity select the expected ladder.
3. Verify the approver is distinct from the executor and requester where required.
4. Check notification delivery and durable retry state.
5. Treat expiration as an audited no-op.

## Communications

Operational alerts, approval requests, and incident lifecycle notices use
different message classes and RBAC floors. Channels receive the minimum context
needed to act: incident ID, scope, severity, evidence links, requested decision,
and expiry. Secrets and raw customer data stay out of messages.

## Next steps

| To learn about | Read |
|----------------|------|
| How approvals work | [Approvals and channels](../concepts/approvals-and-channels.md) |
| The escalation contract | [Escalation and Standing Authority](../../roadmap/decisioning/escalation-and-standing-authority.md) |
| Channel routing | [Channels and notifications](../../roadmap/interfaces/channels-and-notifications.md) |
| Incident ownership | [Incident management](incident-management.md) |
