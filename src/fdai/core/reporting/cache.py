"""Optional TTL cache in front of :class:`ReportEngine`.

Composition-root helper - drop-in wrapper that memoizes
:meth:`ReportEngine.render` for identical ``(report_id, variables)``
pairs within a configurable window. Useful for busy read-API endpoints
where a report is hit many times per second by a dashboard poll.

The cache is process-local and unbounded is prevented by
``max_entries`` + LRU eviction on write. It does NOT try to hash a
resolved ``DataSet`` - the wrapper caches the final
:class:`RenderedReport` and its ``generated_at`` records the cached
time.

Safety: the cache is opt-in. Upstream :class:`ReportEngine` never
caches. A fork wires this only when the freshness contract of every
wired datasource is stable-enough for staleness == TTL.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass

from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.models import RenderedReport


@dataclass(frozen=True, slots=True)
class ReportCacheEntry:
    """One cached render + the wall-clock it was produced at."""

    report: RenderedReport
    stored_at: float


class InMemoryReportCache:
    """LRU-with-TTL wrapper around a :class:`ReportEngine`.

    Not thread-safe (the read-API runs one asyncio loop). If a future
    fork needs multi-thread access, wrap externally.
    """

    __slots__ = ("_engine", "_ttl_seconds", "_max_entries", "_store")

    def __init__(
        self,
        engine: ReportEngine,
        *,
        ttl_seconds: float = 30.0,
        max_entries: int = 128,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds MUST be > 0")
        if max_entries < 1:
            raise ValueError("max_entries MUST be >= 1")
        self._engine = engine
        self._ttl_seconds = float(ttl_seconds)
        self._max_entries = int(max_entries)
        self._store: OrderedDict[tuple[str, tuple[tuple[str, str], ...]], ReportCacheEntry] = (
            OrderedDict()
        )

    # Forward the standard engine facade so a caller does not know it is
    # talking to a cache.

    def catalog(self):  # type: ignore[no-untyped-def]
        return self._engine.catalog()

    def widget_registry(self):  # type: ignore[no-untyped-def]
        return self._engine.widget_registry()

    def datasource_registry(self):  # type: ignore[no-untyped-def]
        return self._engine.datasource_registry()

    def config(self):  # type: ignore[no-untyped-def]
        return self._engine.config()

    def health(self) -> dict[str, object]:
        base = self._engine.health()
        base["cache"] = {
            "ttl_seconds": self._ttl_seconds,
            "max_entries": self._max_entries,
            "size": len(self._store),
        }
        return base

    async def render(
        self,
        report_id: str,
        *,
        variables: Mapping[str, str] | None = None,
    ) -> RenderedReport:
        key = (report_id, tuple(sorted((variables or {}).items())))
        entry = self._store.get(key)
        now = time.monotonic()
        if entry is not None and (now - entry.stored_at) <= self._ttl_seconds:
            # Refresh LRU order without touching the entry payload.
            self._store.move_to_end(key)
            return entry.report
        rendered = await self._engine.render(report_id, variables=variables)
        self._store[key] = ReportCacheEntry(report=rendered, stored_at=now)
        self._store.move_to_end(key)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)
        return rendered

    def invalidate(self, report_id: str | None = None) -> None:
        """Drop cached renders.

        ``report_id=None`` clears the entire cache; supplying an id
        clears every entry for that report (across variable
        combinations).
        """
        if report_id is None:
            self._store.clear()
            return
        stale = [key for key in self._store if key[0] == report_id]
        for key in stale:
            self._store.pop(key, None)


__all__ = ["InMemoryReportCache", "ReportCacheEntry"]
