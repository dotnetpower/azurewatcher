"""Pure rollups of recorded LLM invocations into cost summaries.

These functions turn a flat list of :class:`LlmInvocation` records into
the three views the operator asks for: **per conversation** (grouped by
``correlation_id``), **per day**, and **per month**. They are pure - no
I/O, no clock - so they are trivially testable and deterministic; the
read-API and console call them over whatever records a
:class:`~fdai.core.metering.sink.MeteringSink` implementation returns.

Cost is summed as :class:`Decimal` and only the *known* costs contribute
to the total; a summary reports ``priced_invocations`` alongside
``invocations`` so an operator can see how much of the spend is
grounded in configured prices versus unpriced (unknown) calls.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from fdai.core.metering.records import LlmInvocation
from fdai.core.metering.usage import TokenUsage


@dataclass(frozen=True, slots=True)
class UsageSummary:
    """Aggregate tokens + cost for one group of invocations.

    ``key`` is the group label (a ``correlation_id`` or a ``YYYY-MM-DD``
    / ``YYYY-MM`` bucket). ``cost`` is the sum of the *known* costs;
    ``priced_invocations`` counts how many of the ``invocations`` carried
    a price, so a partly-unpriced group is transparent rather than
    silently under-reported.
    """

    key: str
    invocations: int
    priced_invocations: int
    usage: TokenUsage
    cost: Decimal
    currency: str

    @property
    def has_unpriced(self) -> bool:
        """True when at least one invocation in the group had no configured price."""
        return self.priced_invocations < self.invocations


def _summarize_group(key: str, records: Iterable[LlmInvocation]) -> UsageSummary:
    usage = TokenUsage.zero()
    cost = Decimal(0)
    invocations = 0
    priced = 0
    currency = "USD"
    for record in records:
        invocations += 1
        usage = usage + record.usage
        if record.cost is not None:
            cost += record.cost
            priced += 1
    return UsageSummary(
        key=key,
        invocations=invocations,
        priced_invocations=priced,
        usage=usage,
        cost=cost,
        currency=currency,
    )


def _group_by(
    records: Iterable[LlmInvocation], key_of: Callable[[LlmInvocation], str]
) -> tuple[UsageSummary, ...]:
    grouped: dict[str, list[LlmInvocation]] = {}
    for record in records:
        grouped.setdefault(key_of(record), []).append(record)
    return tuple(
        _summarize_group(key, grouped[key]) for key in sorted(grouped)
    )


def summarize_by_conversation(
    records: Iterable[LlmInvocation],
) -> tuple[UsageSummary, ...]:
    """One summary per ``correlation_id`` (a conversation / event), sorted by id."""
    return _group_by(records, lambda r: r.correlation_id)


def summarize_by_day(records: Iterable[LlmInvocation]) -> tuple[UsageSummary, ...]:
    """One summary per UTC calendar day (``YYYY-MM-DD``), sorted chronologically."""
    return _group_by(records, lambda r: r.day_bucket)


def summarize_by_month(records: Iterable[LlmInvocation]) -> tuple[UsageSummary, ...]:
    """One summary per UTC calendar month (``YYYY-MM``), sorted chronologically."""
    return _group_by(records, lambda r: r.month_bucket)


def summarize_total(records: Iterable[LlmInvocation]) -> UsageSummary:
    """A single grand-total summary across every record (key ``"total"``)."""
    return _summarize_group("total", records)


def summaries_as_mapping(summaries: Iterable[UsageSummary]) -> tuple[Mapping[str, object], ...]:
    """Render summaries as JSON-serialisable dicts for the read-API boundary.

    ``cost`` is emitted as a ``str`` so the exact decimal survives JSON
    (floats would reintroduce the rounding drift Decimal avoids).
    """
    return tuple(
        {
            "key": s.key,
            "invocations": s.invocations,
            "priced_invocations": s.priced_invocations,
            "prompt_tokens": s.usage.prompt_tokens,
            "completion_tokens": s.usage.completion_tokens,
            "total_tokens": s.usage.total_tokens,
            "cost": str(s.cost),
            "currency": s.currency,
            "has_unpriced": s.has_unpriced,
        }
        for s in summaries
    )


__all__ = [
    "UsageSummary",
    "summaries_as_mapping",
    "summarize_by_conversation",
    "summarize_by_day",
    "summarize_by_month",
    "summarize_total",
]
