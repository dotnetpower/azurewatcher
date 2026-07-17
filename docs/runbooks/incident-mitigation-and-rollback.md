---
title: Incident Mitigation and Rollback Runbook
description: A template for applying a governed mitigation and verifying rollback or recovery.
---

# Incident Mitigation and Rollback Runbook

Use this template after investigation produces a grounded mitigation proposal.

## Procedure

1. Confirm incident, proposal, `ActionType`, mode, scope, owner, and approver.
2. Run policy, what-if, dependency, lock, and blast-radius checks.
3. Confirm stop conditions, rollback contract, and recovery verification.
4. Obtain the required verdict and distinct approval.
5. Execute only through the authorized executor and delivery path.
6. Verify effect; stop or roll back when any declared condition fires.
7. Record terminal state, remaining impact, and incident transition.

## Stop conditions

Stop on stale evidence, lock failure, scope expansion, policy denial, missing
audit writer, unavailable rollback, or unexpected dependency impact.

## Evidence

Record dry-run output, verdict, approval, executor, delivery reference, health
checks, rollback reference, and final incident state.
