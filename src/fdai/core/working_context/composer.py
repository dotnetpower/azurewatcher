"""WorkingContextComposer - the pure policy that bounds the prompt.

Given the full set of candidate transcript entries (verbatim turns,
rolling summaries, retrieved snippets, typed-pipeline facts) and a
:class:`~fdai.core.working_context.types.ContextBudget`, decide which
entries fit under the token budget and in what prompt order. The lossless
memory of record is untouched; this only chooses the *projection* sent to
the model on one turn.

It mirrors :mod:`fdai.core.quality_gate.escalation_ladder` and
:mod:`fdai.core.quality_gate.debate_router`: a frozen config + a
stateless, deterministic function, so the policy is testable and
auditable on its own with no I/O.

Hardening invariants
--------------------
- **Constants survive compaction.** ``pinned`` entries are included
  before any budgeting; if the pinned set alone overflows the history
  budget the composer raises
  :class:`~fdai.core.working_context.types.WorkingContextError` (fail
  closed) rather than silently dropping a safety constraint.
- **Bounded growth.** With verbatim + retrieval capped by ratio and
  summaries folding older turns hierarchically, the assembled context is
  ``O(1)`` in the session length even though the memory of record is
  ``O(L)``. No number-of-turns limit is used anywhere.
- **Deterministic.** Same inputs -> same projection and manifest. No
  wall-clock reads, no randomness; an audited assembly replays
  identically from the stored entries.
- **``core/``-safe.** Imports only stdlib + sibling ``types``. No
  ``delivery.*`` import, no LLM SDK, no token estimator (callers pre-
  estimate ``TranscriptEntry.tokens`` at the boundary).

Design reference:
- ``docs/roadmap/interfaces/operator-console.md`` section 6.
- ``docs/roadmap/decisioning/prompt-composition.md`` (Operator Memory / layers).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from fdai.core.working_context.types import (
    ContextBudget,
    ContextManifest,
    EntryKind,
    TranscriptEntry,
    WorkingContext,
    WorkingContextError,
)

# Prompt ordering: oldest / broadest context first, freshest verbatim
# last, so the delivery adapter maps the tuple straight onto the chat
# messages array. Pinned constraints sit closest to the system prompt.
_GROUP_ORDER: dict[EntryKind, int] = {
    EntryKind.SUMMARY: 1,
    EntryKind.RETRIEVED: 2,
    EntryKind.TYPED_FACT: 3,
    EntryKind.VERBATIM: 4,
}


def _fill(
    candidates: Iterable[TranscriptEntry],
    tier_budget: int,
    carry: int,
    chosen: set[str],
) -> tuple[list[TranscriptEntry], int]:
    """Greedily pick candidates (already in priority order) under budget.

    ``carry`` is unused budget spilled from a higher-priority tier. The
    scan is order-preserving greedy: an entry that does not fit is
    skipped and later (smaller) entries still get a chance, so one large
    turn never starves the rest of its tier. Returns the picked entries
    and the leftover budget to spill onward.
    """

    budget = tier_budget + carry
    picked: list[TranscriptEntry] = []
    used = 0
    for entry in candidates:
        if entry.entry_id in chosen:
            continue
        if used + entry.tokens <= budget:
            picked.append(entry)
            used += entry.tokens
            chosen.add(entry.entry_id)
    return picked, budget - used


def compose_working_context(
    *,
    budget: ContextBudget,
    entries: Sequence[TranscriptEntry],
) -> WorkingContext:
    """Assemble the bounded working context for one turn.

    ``entries`` is every candidate from the memory of record the caller
    considers relevant this turn: recent verbatim turns, hierarchical
    summaries of everything older, relevance-retrieved snippets, and
    deterministic typed-pipeline facts. Classification is by
    :class:`~fdai.core.working_context.types.EntryKind`; ``pinned`` cuts
    across kinds.

    Selection order (each tier spills unused budget to the next):

    1. ``pinned`` - forced, before any budgeting (fail closed on overflow).
    2. ``TYPED_FACT`` - deterministic trusted context, newest first.
    3. ``VERBATIM`` - newest first.
    4. ``RETRIEVED`` - most relevant first (dedup against already chosen).
    5. ``SUMMARY`` - broadest (highest level) first, newest first.
    """

    pinned = [e for e in entries if e.pinned]
    rest = [e for e in entries if not e.pinned]

    typed = sorted(
        (e for e in rest if e.kind is EntryKind.TYPED_FACT),
        key=lambda e: -e.sequence,
    )
    verbatim = sorted(
        (e for e in rest if e.kind is EntryKind.VERBATIM),
        key=lambda e: -e.sequence,
    )
    retrieved = sorted(
        (e for e in rest if e.kind is EntryKind.RETRIEVED),
        key=lambda e: (-(e.relevance or 0.0), -e.sequence),
    )
    summaries = sorted(
        (e for e in rest if e.kind is EntryKind.SUMMARY),
        key=lambda e: (-e.level, -e.sequence),
    )

    history = budget.history_budget
    chosen: set[str] = set()

    # 1. Pinned first - forced. Overflow is a config error, not a drop.
    pinned_tokens = sum(e.tokens for e in pinned)
    if pinned_tokens > history:
        raise WorkingContextError(
            "pinned entries exceed the history budget: "
            f"pinned_tokens={pinned_tokens}, history_budget={history}"
        )
    for e in pinned:
        chosen.add(e.entry_id)
    remaining = history - pinned_tokens

    # 2-5. Tier budgets carved from the remaining history budget; unused
    # budget spills to the next tier so a short session fills with
    # verbatim rather than padding with summaries.
    typed_budget = int(remaining * budget.typed_fact_ratio)
    verbatim_budget = int(remaining * budget.verbatim_ratio)
    retrieval_budget = int(remaining * budget.retrieval_ratio)
    summary_budget = int(remaining * budget.summary_ratio)

    typed_sel, carry = _fill(typed, typed_budget, 0, chosen)
    verbatim_sel, carry = _fill(verbatim, verbatim_budget, carry, chosen)
    retrieved_sel, carry = _fill(retrieved, retrieval_budget, carry, chosen)
    summary_sel, _carry = _fill(summaries, summary_budget, carry, chosen)

    selected = [*pinned, *typed_sel, *verbatim_sel, *retrieved_sel, *summary_sel]
    ordered = tuple(
        sorted(
            selected,
            key=lambda e: (0 if e.pinned else _GROUP_ORDER[e.kind], e.sequence),
        )
    )

    dropped = tuple(e.entry_id for e in entries if e.entry_id not in chosen)
    manifest = ContextManifest(
        verbatim_ids=tuple(e.entry_id for e in verbatim_sel),
        summary_ids=tuple(e.entry_id for e in summary_sel),
        retrieved_ids=tuple(e.entry_id for e in retrieved_sel),
        pinned_ids=tuple(e.entry_id for e in pinned),
        typed_fact_ids=tuple(e.entry_id for e in typed_sel),
        verbatim_tokens=sum(e.tokens for e in verbatim_sel),
        summary_tokens=sum(e.tokens for e in summary_sel),
        retrieved_tokens=sum(e.tokens for e in retrieved_sel),
        pinned_tokens=pinned_tokens,
        typed_fact_tokens=sum(e.tokens for e in typed_sel),
        dropped_ids=dropped,
    )
    return WorkingContext(entries=ordered, manifest=manifest)


__all__ = ["compose_working_context"]
