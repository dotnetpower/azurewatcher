"""Tests for :class:`LatencyRoutedChatBackend` warm-up + p50 selection."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from fdai.delivery.read_api.chat import LatencyRoutedChatBackend


class _FixedLatencyBackend:
    """Async backend that sleeps a fixed amount so the router measures it."""

    def __init__(self, *, model: str, delay_ms: int) -> None:
        self._model = model
        self._delay_ms = delay_ms
        self.calls = 0

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, Any]:
        self.calls += 1
        await asyncio.sleep(self._delay_ms / 1000)
        return {"answer": "ok", "model": self._model}


class _RaisingBackend:
    def __init__(self, *, model: str) -> None:
        self._model = model
        self.calls = 0

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, Any]:
        self.calls += 1
        raise RuntimeError("upstream down")


class TestRouterConstruction:
    def test_requires_two_or_more_candidates(self) -> None:
        only = _FixedLatencyBackend(model="only", delay_ms=1)
        with pytest.raises(ValueError, match=">= 2"):
            LatencyRoutedChatBackend(candidates=[("only", only)])

    def test_rejects_duplicate_names(self) -> None:
        a = _FixedLatencyBackend(model="dup", delay_ms=1)
        b = _FixedLatencyBackend(model="dup", delay_ms=1)
        with pytest.raises(ValueError, match="unique"):
            LatencyRoutedChatBackend(candidates=[("dup", a), ("dup", b)])


class TestRouterWarmupAndSelection:
    async def _make_router(self) -> tuple[
        LatencyRoutedChatBackend, _FixedLatencyBackend, _FixedLatencyBackend, _FixedLatencyBackend
    ]:
        fast = _FixedLatencyBackend(model="fast", delay_ms=5)
        mid = _FixedLatencyBackend(model="mid", delay_ms=25)
        slow = _FixedLatencyBackend(model="slow", delay_ms=60)
        router = LatencyRoutedChatBackend(
            candidates=[("fast", fast), ("mid", mid), ("slow", slow)],
        )
        return router, fast, mid, slow

    async def test_warmup_rotates_every_candidate_before_pinning(self) -> None:
        router, fast, mid, slow = await self._make_router()
        # Fire 6 turns - warmup requires 2 samples per candidate (3*2=6).
        picks: list[str] = []
        for _ in range(6):
            reply = await router.answer(prompt="hi", view_context={}, history=[])
            picks.append(reply["router"]["chose"])
        # Every candidate got exactly two calls during warm-up.
        assert fast.calls == 2
        assert mid.calls == 2
        assert slow.calls == 2
        # And warm-up reason is stamped on every one of those turns.
        assert all(picks.count(name) == 2 for name in ("fast", "mid", "slow"))

    async def test_steady_state_prefers_lowest_p50(self) -> None:
        router, fast, mid, slow = await self._make_router()
        # Warm-up first.
        for _ in range(6):
            await router.answer(prompt="hi", view_context={}, history=[])
        # After warm-up the fast backend has the lowest p50; the next 3
        # turns should all pick it.
        for _ in range(3):
            reply = await router.answer(prompt="hi", view_context={}, history=[])
            assert reply["router"]["chose"] == "fast"
            assert reply["router"]["reason"] == "lowest-p50"
            assert reply["model"] == "fast"
        assert fast.calls == 5  # 2 warmup + 3 steady
        assert mid.calls == 2
        assert slow.calls == 2

    async def test_response_carries_full_candidate_stats(self) -> None:
        router, *_ = await self._make_router()
        for _ in range(6):
            await router.answer(prompt="hi", view_context={}, history=[])
        reply = await router.answer(prompt="hi", view_context={}, history=[])
        stats = {c["deployment"]: c for c in reply["router"]["candidates"]}
        assert set(stats.keys()) == {"fast", "mid", "slow"}
        assert stats["fast"]["samples"] >= 2
        assert stats["fast"]["p50_ms"] < stats["slow"]["p50_ms"]

    async def test_stats_expose_p95_and_history_for_sparkline(self) -> None:
        router, *_ = await self._make_router()
        # Run enough turns to fill the rolling window at least partially.
        for _ in range(9):
            await router.answer(prompt="hi", view_context={}, history=[])
        stats = {c["deployment"]: c for c in router.stats()}
        for name in ("fast", "mid", "slow"):
            entry = stats[name]
            assert entry["samples"] == len(entry["history_ms"])
            assert entry["samples"] > 0
            # p95 >= p50 by definition (nearest-rank).
            assert entry["p95_ms"] >= entry["p50_ms"]
            # history_ms carries integers in the router's window bounds.
            for sample in entry["history_ms"]:
                assert isinstance(sample, int)
                assert sample >= 0


class TestRouterFailureHandling:
    async def test_failure_penalizes_candidate_and_reraises(self) -> None:
        good = _FixedLatencyBackend(model="good", delay_ms=5)
        bad = _RaisingBackend(model="bad")
        router = LatencyRoutedChatBackend(
            candidates=[("bad", bad), ("good", good)],  # ordered so ties go to "bad" first
        )
        # First warm-up call goes to whichever has fewer samples; both have 0.
        # Tie-breaking is by name, so "bad" is served first and raises.
        with pytest.raises(RuntimeError, match="upstream down"):
            await router.answer(prompt="hi", view_context={}, history=[])
        assert bad.calls == 1
        # A penalty sample was recorded so the router does not re-pin to "bad".
        stats = {c["deployment"]: c for c in router.stats()}
        assert stats["bad"]["samples"] == 1
        assert stats["bad"]["p50_ms"] is not None
        assert stats["bad"]["p95_ms"] is not None
        assert stats["bad"]["p50_ms"] >= 20_000  # penalty is 30_000ms


class TestRouterConcurrencyFairness:
    """Concurrent turns during warm-up MUST spread across candidates.

    Without in-flight accounting, N async turns arriving at once all read
    the same "coldest" candidate from ``_pick`` and stampede one backend,
    starving the warm-up rotation.
    """

    async def test_concurrent_warmup_spreads_across_candidates(self) -> None:
        # Each backend sleeps enough that all three warm-up picks are
        # in-flight simultaneously when the next pick happens.
        fast = _FixedLatencyBackend(model="fast", delay_ms=30)
        mid = _FixedLatencyBackend(model="mid", delay_ms=30)
        slow = _FixedLatencyBackend(model="slow", delay_ms=30)
        router = LatencyRoutedChatBackend(
            candidates=[("fast", fast), ("mid", mid), ("slow", slow)],
        )
        # Fire three warm-up picks in parallel.
        await asyncio.gather(
            router.answer(prompt="a", view_context={}, history=[]),
            router.answer(prompt="b", view_context={}, history=[]),
            router.answer(prompt="c", view_context={}, history=[]),
        )
        # Every candidate saw exactly one call - not three on "fast".
        assert fast.calls == 1
        assert mid.calls == 1
        assert slow.calls == 1


class TestRouterCleanup:
    class _WithClient:
        def __init__(self) -> None:
            self.closed = False
            self._http = self  # so getattr(backend, "_http", None) returns it

        async def aclose(self) -> None:
            self.closed = True

        async def answer(
            self,
            *,
            prompt: str,  # noqa: ARG002
            view_context: dict[str, Any],  # noqa: ARG002
            history: list[dict[str, str]],  # noqa: ARG002
        ) -> dict[str, Any]:  # pragma: no cover - unused in this test
            return {"answer": "ok", "model": "x"}

    async def test_aclose_closes_every_candidate_client(self) -> None:
        a = self._WithClient()
        b = self._WithClient()
        router = LatencyRoutedChatBackend(candidates=[("a", a), ("b", b)])
        await router.aclose()
        assert a.closed is True
        assert b.closed is True

    async def test_aclose_tolerates_backends_without_client(self) -> None:
        # A backend that never allocated a client (no ``_http`` attr) must
        # not break the cleanup path.
        a = _FixedLatencyBackend(model="a", delay_ms=1)
        b = _FixedLatencyBackend(model="b", delay_ms=1)
        router = LatencyRoutedChatBackend(candidates=[("a", a), ("b", b)])
        await router.aclose()  # must not raise
