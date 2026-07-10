"""Tests for :mod:`fdai.core.metering.aggregate`."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fdai.core.metering.aggregate import (
    summaries_as_mapping,
    summarize_by_conversation,
    summarize_by_day,
    summarize_by_month,
    summarize_total,
)
from fdai.core.metering.records import InvocationMode, LlmInvocation
from fdai.core.metering.usage import TokenUsage

_UTC = UTC


def _inv(
    *,
    when: datetime,
    corr: str,
    prompt: int,
    completion: int,
    cost: Decimal | None,
) -> LlmInvocation:
    return LlmInvocation(
        occurred_at=when,
        correlation_id=corr,
        capability_id="t2.reasoner.primary",
        model_key="gpt-4o",
        tier="T2",
        mode=InvocationMode.ENFORCE,
        usage=TokenUsage(prompt_tokens=prompt, completion_tokens=completion),
        cost=cost,
    )


_RECORDS = [
    _inv(
        when=datetime(2026, 7, 9, 10, tzinfo=_UTC),
        corr="evt-a",
        prompt=1000,
        completion=200,
        cost=Decimal("0.30"),
    ),
    _inv(
        when=datetime(2026, 7, 9, 11, tzinfo=_UTC),
        corr="evt-a",
        prompt=500,
        completion=100,
        cost=Decimal("0.20"),
    ),
    _inv(
        when=datetime(2026, 7, 10, 9, tzinfo=_UTC),
        corr="evt-b",
        prompt=800,
        completion=50,
        cost=None,  # unpriced model
    ),
]


def test_by_conversation_rolls_up_and_sorts() -> None:
    summaries = summarize_by_conversation(_RECORDS)
    assert [s.key for s in summaries] == ["evt-a", "evt-b"]
    a = summaries[0]
    assert a.invocations == 2
    assert a.priced_invocations == 2
    assert a.usage.total_tokens == 1800
    assert a.cost == Decimal("0.50")
    assert a.has_unpriced is False


def test_unpriced_group_is_transparent() -> None:
    b = summarize_by_conversation(_RECORDS)[1]
    assert b.invocations == 1
    assert b.priced_invocations == 0
    assert b.cost == Decimal("0")
    assert b.has_unpriced is True


def test_by_day_and_month_bucketing() -> None:
    days = summarize_by_day(_RECORDS)
    assert [s.key for s in days] == ["2026-07-09", "2026-07-10"]
    assert days[0].cost == Decimal("0.50")

    months = summarize_by_month(_RECORDS)
    assert [s.key for s in months] == ["2026-07"]
    assert months[0].invocations == 3
    assert months[0].usage.total_tokens == 2650


def test_total_summary() -> None:
    total = summarize_total(_RECORDS)
    assert total.key == "total"
    assert total.invocations == 3
    assert total.priced_invocations == 2
    assert total.cost == Decimal("0.50")


def test_empty_records() -> None:
    assert summarize_by_day([]) == ()
    total = summarize_total([])
    assert total.invocations == 0
    assert total.cost == Decimal("0")


def test_summaries_as_mapping_serialises_cost_as_str() -> None:
    rows = summaries_as_mapping(summarize_by_conversation(_RECORDS))
    assert rows[0]["cost"] == "0.50"
    assert rows[0]["total_tokens"] == 1800
    assert rows[1]["has_unpriced"] is True
