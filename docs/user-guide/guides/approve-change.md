---
title: Approve a change
description: How to review and approve (or reject) a change FDAI has queued for human-in-the-loop decision.
---

# Approve a change

When a proposed change lands in the HIL tier, FDAI pauses execution and
asks a human. This guide walks through the operator's side of that
interaction - what the request looks like, what to check before approving,
and what happens after each verdict.

## What a HIL request looks like

You receive the request through the notification channel your deployment
configured (Teams Adaptive Card, PR review request, email, pager, etc.).
Every HIL request carries the same core payload regardless of channel:

- **Event summary** - what triggered the change (drift, cost anomaly, DR
  drill, etc.) and which resource is affected.
- **Proposed action** - the exact change FDAI would apply, either as a
  ready-to-review PR or as a serialised action envelope.
- **Risk classification** - why this landed in HIL rather than AUTO: the
  specific dimension (blast radius, novelty, reversibility, signal source)
  that raised the tier.
- **Rollback preview** - the pre-computed rollback path that would run if
  the change is approved and later needs to be reverted.
- **Stop-condition** - the measurable state that will halt the change if the
  world reacts badly after approval.
- **Audit link** - a deep link to the audit-log entry so you can see the
  event chain that produced this decision.

## What to check before approving

Five quick checks in order of importance:

1. **Does the risk classification look right?** If the proposed action feels
   too aggressive for the stated risk, the classification rule may need
   attention - reject and escalate rather than approve blindly.
2. **Blast radius** - confirm the scope cap ("this resource group only",
   "batch of 5 VMs", etc.) matches what you actually want to change.
3. **Rollback path** - the rollback preview should be non-empty and
   plausible. An empty or handwavy rollback is a design bug in the action,
   not something to approve around.
4. **Stop-condition** - should be observable in the metrics you already
   watch. If it references a metric you cannot see, reject.
5. **Grounding (T2 only)** - if this was a T2 decision, verify the cited
   rules or documents in the audit-log entry actually support the proposed
   action.

## Verdicts and their consequences

- **Approve** - the change executes with all its safety invariants
  (stop-condition, rollback path, blast-radius cap, audit entry). The audit
  log records who approved, when, and any comment you left.
- **Reject** - the change is discarded. An audit entry is still written
  (approver, reason, event id) so the discovery loop can learn from the
  pattern.
- **Timeout** - HIL requests carry a configurable timeout. On expiry the
  change is discarded exactly as if it were rejected; there is no
  auto-approve on timeout, ever.

## Break-glass approvals

There is a Break-Glass role for the rare case where an approver has to bypass
DENY. Every Break-Glass use is prominently audited, notifies the on-call
team, and is expected to be justified after the fact. It is not an
alternative to fixing the underlying rule.

## Next steps

| To learn about | Read |
|----------------|------|
| How the classification in front of you was produced | [../concepts/risk-tiers.md](../concepts/risk-tiers.md) |
| How to trace what happened after your verdict | [read-audit-log.md](read-audit-log.md) |
| What to do if a rule keeps producing bad HIL cards | [override-a-rule.md](override-a-rule.md) |
| The channels that carry HIL requests | [../../roadmap/interfaces/channels-and-notifications.md](../../roadmap/interfaces/channels-and-notifications.md) |
