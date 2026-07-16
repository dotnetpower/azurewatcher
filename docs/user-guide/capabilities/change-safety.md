---
title: Change Safety
description: How FDAI keeps every proposed change safe - policy-gated, risk-classified, and delivered as an auditable pull request.
derives_from:
  - source: docs/roadmap/architecture/goals-and-metrics.md
    sha: eddf9552f2f88f4e1bec24b2521b7656ed87d103
---

# Change Safety

Every change to your cloud - an infrastructure-as-code pull request, a drifted
configuration, a policy violation - is evaluated before it can reach production.
FDAI treats change safety as a deterministic gate first and a judgment call only
when the deterministic tier cannot decide, so the repeatable majority of changes
resolve without a human and without a model.

## What you get

- **Policy gates on every change.** Each proposed change is dry-run against
  policy-as-code (a what-if evaluation) before anything is applied.
- **Drift caught and remediated.** Configuration that diverges from its declared
  state is detected, classified, and either auto-corrected or raised for review.
- **High-risk changes pause for you.** The risk gate routes low-risk changes to
  auto-merge and high-risk changes to human-in-the-loop (HIL) approval.
- **Audit and rollback for free.** Actions ship as remediation pull requests, so
  the change record and the rollback path already live in git.

## How FDAI keeps a change safe

<!-- fdai:steps -->

1. **Detect.** A resource change, an activity-log event, or a drift signal enters
   the control loop as one normalized event.
2. **Dry-run against policy.** The deterministic tier evaluates the change with
   what-if against policy-as-code - no mutation yet.
3. **Classify the risk.** The risk gate places the change on the
   [risk-classification](../../roadmap/decisioning/risk-classification.md) table:
   auto, HIL, or deny.
4. **Auto-merge or ask.** Low-risk changes merge automatically; high-risk changes
   wait for [approval](../guides/approve-change.md) through your channel.
5. **Deliver and audit.** The change ships as a pull request with a rollback
   reference, and every decision - including denies and no-ops - is recorded.

## Proof, not promises

Change safety is measured, never asserted. FDAI reports these against a measured
baseline on a frozen scenario set (see
[goals and metrics](../../roadmap/architecture/goals-and-metrics.md)):

- **Change lead time** - the time from change request to merge - is a directional
  target to shorten, reported as median and p90, not only the mean.
- **Change failure rate** is a guard metric: it MUST NOT increase. A rise demotes
  the action from enforce back to shadow automatically.
- **Policy-violation escapes** must be exactly zero. Any autonomous change that
  violates policy and reaches enforce blocks the release.

New gates always ship in [shadow mode](../concepts/shadow-then-enforce.md) first -
judging and logging without mutating - and are promoted to enforce only after they
clear their promotion gate.

## Related

<!-- fdai:cards -->

- [Deterministic first](../concepts/deterministic-first.md) - Why the repeatable majority stays rule-driven.
- [Risk tiers](../concepts/risk-tiers.md) - How a change is routed to auto, HIL, or deny.
- [Ontology-driven automation](../concepts/ontology-driven-automation.md) - The typed actions a change instantiates.
- [Approve a change](../guides/approve-change.md) - The operator side of a HIL approval.
- [Deploy and onboard](../../roadmap/deployment/deploy-and-onboard.md) - Bring FDAI into your environment.
