---
title: Deterministic first
description: Why AIOpsPilot resolves the repeatable majority with rules and reserves LLM inference for the ambiguous minority.
---

# Deterministic first

**Deterministic first** is AIOpsPilot's central design commitment: any event
that a policy, rule, or checklist can decide is decided that way, and no LLM
runs on it. LLM inference is reserved for the residual minority that the
deterministic layer explicitly abstains on.

## The problem this addresses

If you route every cloud-operations event to a language model, three things
break:

- **Cost** — inference over the full event volume is expensive and grows with
  traffic, even though most events are boringly repeatable.
- **Predictability** — the same event on Monday and Wednesday can get
  different decisions from the same model. That is fine for a novel case but
  disastrous for a routine one.
- **Auditability** — "the model chose to auto-approve" is hard to
  defend after an incident. "The rule matched policy X, version 1.4" is not.

## How AIOpsPilot resolves it

Every incoming event flows through a **trust router** that picks the lowest
tier competent to decide the case:

- **T0 — deterministic (target ~70–80% of events)**. Policy-as-code (OPA),
  checklists, thresholds, allow/deny lists. If a rule fires, that rule's
  verdict wins. No model call, no ambiguity.
- **T1 — lightweight reuse (target ~15–20%)**. Embedding similarity to
  historical incidents, cheap classifiers, small-model retrieval. Still no
  frontier LLM, still fully explainable.
- **T2 — deep reasoning (target ~5–10%)**. Only novel or intrinsically
  ambiguous cases. Frontier LLMs generate; a **verifier** re-checks the
  proposed action against policy-as-code and grounds it in retrieved
  documents. The LLM proposes, the verifier disposes.

## What this means in practice

- The rule catalog is a **first-class asset**, not a nice-to-have — it
  determines how much of the traffic never reaches an LLM.
- Every T2 decision cites its sources (grounding). If those citations don't
  survive the verifier, the case escalates to a human, not to a "best guess".
- Fork-friendly: to raise your T0 coverage, you add rules; you don't retrain
  a model.

## Related

- [Risk tiers](../risk-tiers/) — how the outcome of T0/T1/T2 gets classified
  into auto vs HIL.
- Full engineering detail in the roadmap:
  [architecture.instructions.md](../../reference/roadmap/) → *3-Tier Trust
  Router*.
