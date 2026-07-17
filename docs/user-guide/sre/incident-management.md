---
title: Incident Management
description: How FDAI creates, owns, transitions, measures, and closes a first-class incident.
---

# Incident Management

An incident is the durable operating record that connects correlated signals,
ownership, investigation, response, recovery, and postmortem evidence. FDAI
uses an explicit lifecycle instead of treating an incident as a label attached
to an alert.

## Incident lifecycle

```text
open -> triaging -> mitigated -> resolved -> closed
```

Transitions are validated by a state machine and written idempotently. A stale
expected state raises a conflict instead of overwriting a newer operator or
automation decision.

| State | Operator meaning |
|-------|------------------|
| `open` | Correlated evidence created an incident record |
| `triaging` | Ownership and evidence gathering are active |
| `mitigated` | Immediate impact is contained, but recovery is not complete |
| `resolved` | Service recovery is verified |
| `closed` | Follow-up and required post-incident work are complete |

## What the record carries

The incident stores a stable ID, correlation keys, severity, status, source,
owner, timestamps, member references, mitigation summary, and postmortem
reference. Audit entries preserve opens, membership changes, assignments, and
transitions.

Missing ownership, impact, or recovery evidence is shown as unavailable. The
console does not infer those values from display text.

## Create and assign safely

Manual creation requires a contributor-level operator and confirmation of the
proposed severity and correlation keys. Automated correlation derives a stable
incident anchor so repeated delivery opens or updates the same incident.

Assignment changes are audited and notification delivery is durable. A failed
notification does not roll back the lifecycle record, and retry claims prevent
duplicate delivery from becoming duplicate state transitions.

## Triage, mitigate, and resolve

1. Confirm membership, scope, severity, and current owner.
2. Move to `triaging` and start a bounded investigation.
3. Route a mitigation proposal through the typed pipeline and required approval.
4. Mark `mitigated` only when impact containment has evidence.
5. Mark `resolved` only after service recovery is verified.
6. Close after required follow-up, postmortem, and ownership actions are recorded.

## SLA and storm handling

Severity-based acknowledge and resolution targets can be evaluated from the
transition stream. Event storms remain bounded by deterministic incident IDs,
deduplication, and explicit remediation steps; they do not create unlimited
parallel mutations.

## Next steps

| To learn about | Read |
|----------------|------|
| How evidence is gathered | [Triage and investigation](triage-and-investigation.md) |
| How cause is represented | [Root-cause analysis](root-cause-analysis.md) |
| How mitigations remain governed | [Response plans and mitigation](response-plans-and-mitigation.md) |
| How the final record is reviewed | [Postmortems and learning](postmortems-and-learning.md) |
