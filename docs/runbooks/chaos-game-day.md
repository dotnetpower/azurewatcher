---
title: Chaos Game Day Runbook
description: A template for planning, approving, running, and recovering from a bounded chaos experiment.
---

# Chaos Game Day Runbook

Use this template for a promoted scenario inside an approved exercise window.

## Procedure

1. Confirm scenario version, hypothesis, owner, approver, target allowlist, and exercise window.
2. Verify shadow evidence, preflight, steady state, stop conditions, and rollback.
3. Freeze the target set and acquire required locks.
4. Inject through the approved provider while continuously evaluating probes.
5. Abort on scope expansion, protected dependency degradation, stale probes, or duration limit.
6. Roll back, verify recovery, remove temporary resources, and seal the audit record.

## Evidence

Record scenario and catalog versions, targets, approvals, probe samples,
injection times, stop reason, rollback result, recovery time, and unexpected impact.
