---
title: RCA Evidence Collection Runbook
description: A template for assembling a bounded, cited evidence set before accepting a root-cause hypothesis.
---

# RCA Evidence Collection Runbook

Use this template before accepting or publishing an RCA hypothesis.

## Procedure

1. Freeze the incident ID, target resources, time range, and evidence budget.
2. Collect correlated events, deployment changes, metrics, logs, traces, rules, and approved knowledge references.
3. Verify source identity, timestamps, freshness, and access scope.
4. Build the chronology before ranking causes.
5. Require every hypothesis claim to cite the supplied evidence set.
6. Record alternatives, ambiguity, confidence, and abstention reason.

## Stop conditions

Stop when evidence exceeds scope, citations cannot be verified, timestamps are
inconsistent, or a provider response may contain unvouched data. Route an
ungrounded result to human review.

## Evidence

Store opaque references and hashes, not secrets or raw restricted payloads.
