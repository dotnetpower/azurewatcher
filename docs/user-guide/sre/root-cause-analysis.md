---
title: Root-Cause Analysis
description: How FDAI produces tiered, cited root-cause hypotheses and abstains when evidence is insufficient.
---

# Root-Cause Analysis

Root-cause analysis (RCA) explains why an incident may have happened. FDAI
stores RCA as a hypothesis with citations, confidence, tier, and grounding
state. It is evidence for a decision, never permission to execute a change.

## RCA by trust tier

| Tier | Role | Typical evidence |
|------|------|------------------|
| T0 | Direct deterministic cause | Matched rule, violated control, declared remediation |
| T1 | Prior-incident reuse or deterministic causal chain | Resolved incident, ordered change and symptom events, resource dependencies |
| T2 | Grounded reasoning for novel or ambiguous cases | Vouched telemetry, events, rules, knowledge chunks, scenario evidence |

T1 reuse re-verifies the prior cause and learned action against current
evidence. A T1 causal chain requires a preceding change as its root; a window
containing only symptoms abstains instead of inventing a cause.

## Grounding gate

Every citation must come from the evidence set supplied to the reasoner. A
malformed response, fabricated citation, unsupported claim, or confidence below
the configured threshold becomes an abstained hypothesis and routes to human
review.

Telemetry and operator documents are untrusted inputs. Model text cannot
override policy, what-if results, or the deterministic verifier.

## Causal chains

A structured T1 chain preserves root and failure event IDs plus ordered hops.
Each hop records cause and effect references, lead time, relationship, and
confidence. Resource dependency data strengthens related paths and blocks
unrelated links when a graph is available.

Temporal order alone is not certainty. Confidence is bounded, reduced when
multiple roots explain the failure similarly, and determined by the weakest
supported link.

## Read an RCA dossier

Check these elements together:

1. Incident and correlation ID.
2. Tier, outcome, confidence, and grounding state.
3. Citations and evidence freshness.
4. Alternative or ambiguous hypotheses.
5. Structured causal hops when present.
6. Linked response plan, verdict, mode, and rollback reference.

Missing chain data or evidence renders unavailable. The browser does not
reconstruct a more confident explanation than the audit record contains.

## Next steps

| To learn about | Read |
|----------------|------|
| How evidence is bounded | [Triage and investigation](triage-and-investigation.md) |
| How a mitigation is proposed | [Response plans and mitigation](response-plans-and-mitigation.md) |
| How decisions are audited | [Read the audit log](../guides/read-audit-log.md) |
| The detailed RCA contract | [Observability and Detection](../../roadmap/rules-and-detection/observability-and-detection.md) |
