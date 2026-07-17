---
title: Response Plans and Mitigation
description: How FDAI authors, pretests, approves, and routes an incident response plan without bypassing the action pipeline.
---

# Response Plans and Mitigation

An incident response plan (IRP) is a pre-authored, gated response to a class of
alert. It declares the trigger, ordered response steps, activation
requirements, approver role, and notification channels. A plan can propose and
route a mitigation, but it never executes one directly.

## Authoring gate

Every plan starts as a draft. Activation checks that required runbooks,
rollback references, owners, channels, and approval roles are present. A plan
that fails readiness remains inactive.

Pretesting evaluates the plan against similar resolved incidents. The report
shows which historical cases the plan could cover and where required evidence
or steps are missing. Pretest success is evidence for review, not automatic
activation.

## Alert response flow

1. An alert starts a time-bounded investigation.
2. The investigation returns findings and prioritized recommendations.
3. The coordinator selects the highest grounded actionable recommendation.
4. A mitigation proposal is sent to the configured approval gate.
5. An approved proposal re-enters the typed trust and risk pipeline.
6. Teams or Slack receives the governed outcome.

The default approval gate denies. A missing or broken approval binding therefore
produces no action.

## Mitigation is not execution

A response step names an `ActionType`; it does not call an executor. The normal
pipeline still validates preconditions, stop conditions, blast radius,
rollback, mode, lock, identity, and policy. Rejection and timeout terminate as
audited no-ops.

## Failure behavior

- No actionable finding produces no proposal.
- Investigation timeout or exception produces no action and retains an audit-shaped result.
- Approval rejection or timeout produces no-op.
- Routing failure does not become an out-of-band API call.
- Partial execution follows the runbook's declared failure and compensation branch.

## Next steps

| To learn about | Read |
|----------------|------|
| How evidence is gathered | [Triage and investigation](triage-and-investigation.md) |
| How approval routes are selected | [On-call and escalation](on-call-and-escalation.md) |
| How typed actions remain safe | [Ontology-driven automation](../concepts/ontology-driven-automation.md) |
| Operator procedures | [SRE runbooks](../../runbooks/README.md) |
