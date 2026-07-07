---
title: Read the audit log
description: What the append-only audit log records for every autonomous decision, and how to trace an incident back through it.
---

# Read the audit log

The audit log is FDAI's single source of truth for what happened. It
is append-only, immutable, and covers every autonomous decision the control
plane makes - including the ones that ended in a rejection, a timeout, or a
no-op. This guide covers what each entry contains and how to walk backwards
from a symptom to the root event.

## What an entry contains

Every entry records the full lifecycle of one decision. At minimum:

- **Event id** - the stable, idempotency-safe identifier of the source
  event. Multiple decisions from the same event share this id.
- **Tier** - T0 / T1 / T2, so you can tell at a glance whether the decision
  ran deterministically or reached the reasoning tier.
- **Rule / policy / model refs** - for T0 and T1 the rule ids, for T2 the
  model identifier and the cited grounding documents.
- **Verdict** - AUTO / HIL / DENY, plus the classification that produced it.
- **Actor identity** - who or what ran the change. For AUTO this is the
  executor's user-assigned Managed Identity. For HIL, the approving user.
- **Timestamp** - RFC 3339, UTC.
- **Shadow vs enforce mode** - every entry marks whether the capability was
  in shadow at the time. Shadow entries carry the *would-have-been*
  action.
- **Rollback reference** - the id of the rollback plan associated with the
  action, or `none` for actions that had nothing to roll back.

## Tracing an incident

Start with the symptom (a metric spike, an alert, a resource that changed
unexpectedly) and walk backwards:

1. Find the resource in the audit log. Every mutation shows up whether it
   originated from FDAI or from an out-of-band change.
2. Read the latest entry for that resource. It gives you the event id and
   the decision chain that produced the mutation.
3. Follow the event id backwards. Every event with that id is a related
   decision - the same normalized event may have produced a T0 decision,
   an escalation to T1, and a HIL request, all sharing the id.
4. Cross-reference the shadow entries. Even actions that were never
   executed show up in shadow mode with their would-have-been decision, so
   you can see what FDAI proposed vs what a human actually did.

## Replay and post-incident review

The audit log is designed for **judge-only replay**: you can replay any
event through the control plane and see the decisions it would produce
again, without re-executing the underlying action. This is how you diff a
proposed rule change against last month's history before promoting it.

## What is *not* in the audit log

The audit log records decisions and actor references - it never records
secrets, tokens, customer identifiers, or the payload of user data. If you
need diagnostic data, the observability stack (logs, metrics, traces) is
the correct place; each audit entry carries the correlation id that ties
back to those observations.

## Next steps

| To learn about | Read |
|----------------|------|
| The operator interaction that writes HIL entries | [approve-change.md](approve-change.md) |
| Why some entries carry `would-have-been` decisions | [../concepts/shadow-then-enforce.md](../concepts/shadow-then-enforce.md) |
| How to narrow a rule that keeps auditing badly | [override-a-rule.md](override-a-rule.md) |
| The audit-log storage and retention design | [../../roadmap/observability-and-detection.md](../../roadmap/observability-and-detection.md) |
