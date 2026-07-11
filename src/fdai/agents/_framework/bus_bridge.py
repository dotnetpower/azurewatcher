"""Bridge from pantheon dispatch to the ``EventBus`` provider Protocol.

The pantheon in-memory bus (:mod:`fdai.agents.bus`) is a
sync-dispatch tool that runs subscribers inline for tests. Production
runs against the real ``EventBus`` Protocol
(:class:`~fdai.shared.providers.event_bus.EventBus`) - Kafka-wire on
Event Hubs or an alternate broker.

This module gives the pantheon a Protocol-compatible bridge:

- :class:`EventBusBridge` accepts a `PantheonRegistry` + a real
  `EventBus` provider, enforces single-writer publish, injects
  ``producer_principal`` into every published payload, and exposes a
  ``run()`` coroutine that consumes registered subscribers via the
  provider's async iterator.

Idempotency: the pantheon agents already dedup on ``idempotency_key``;
the bridge does not add extra dedup. At-least-once delivery is the
underlying Kafka guarantee.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from fdai.agents._framework.registry import PantheonRegistry
from fdai.shared.providers.event_bus import EventBus, PublishReceipt

_LOG = logging.getLogger(__name__)

Payload = Mapping[str, object]
Handler = Callable[[str, dict[str, object]], Awaitable[None]]

# Kafka key resolver: pantheon agents already put ``resource_id`` on
# mutation payloads and ``correlation_id`` on judgment / audit payloads,
# so the bridge picks whichever is present.
_MUTATION_TOPICS: frozenset[str] = frozenset(
    {"object.action-run", "object.action-attempt", "object.rollback"}
)


def _partition_key(topic: str, payload: Payload) -> str:
    if topic in _MUTATION_TOPICS:
        rid = payload.get("resource_id") or payload.get("correlation_id", "")
        return str(rid)
    return str(payload.get("correlation_id", ""))


@dataclass
class BridgeMetrics:
    """Counters for pantheon bridge observability.

    Exposed via :meth:`EventBusBridge.snapshot` so Heimdall's health
    probe and the KPI collectors can read per-process delivery / failure
    rates without reaching into consumer internals.
    """

    consumers_started: int = 0
    consumers_crashed: int = 0
    consumers_restarted: int = 0
    consumers_gave_up: int = 0
    delivered: int = 0
    handler_errors: int = 0
    dead_lettered: int = 0
    dead_letter_errors: int = 0
    empty_partition_keys: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "consumers_started": self.consumers_started,
            "consumers_crashed": self.consumers_crashed,
            "consumers_restarted": self.consumers_restarted,
            "consumers_gave_up": self.consumers_gave_up,
            "delivered": self.delivered,
            "handler_errors": self.handler_errors,
            "dead_lettered": self.dead_lettered,
            "dead_letter_errors": self.dead_letter_errors,
            "empty_partition_keys": self.empty_partition_keys,
        }


@dataclass
class EventBusBridge:
    """Adapter that lets pantheon agents talk to a real ``EventBus``.

    Substitute wherever tests use :class:`fdai.agents._framework.bus.InMemoryBus`
    at the composition root. The public surface intentionally mirrors
    :class:`InMemoryBus` so agent code stays unchanged.
    """

    provider: EventBus
    registry: PantheonRegistry
    consumer_group_prefix: str = "fdai-pantheon"
    max_consumer_restarts: int = 5
    restart_backoff_base: float = 0.5
    restart_backoff_max: float = 30.0
    shutdown_timeout: float = 5.0
    _subs: dict[str, list[tuple[str, Handler]]] = field(default_factory=lambda: defaultdict(list))
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)
    metrics: BridgeMetrics = field(default_factory=BridgeMetrics)

    # ---- pantheon-style API --------------------------------------------

    def subscribe(self, topic: str, agent_name: str, handler: Handler) -> None:
        self._subs[topic].append((agent_name, handler))

    def snapshot(self) -> dict[str, object]:
        """Return a health snapshot (metrics + live consumer count)."""
        live = sum(1 for t in self._tasks if not t.done())
        return {
            "subscriptions": sum(len(v) for v in self._subs.values()),
            "consumers_live": live,
            "metrics": self.metrics.as_dict(),
        }

    async def publish(
        self,
        principal: str,
        topic: str,
        payload: Payload,
    ) -> PublishReceipt:
        self.registry.assert_can_publish(principal, topic)
        enriched = dict(payload)
        enriched.setdefault("producer_principal", principal)
        key = _partition_key(topic, enriched)
        if not key:
            # An empty key collapses Kafka partitioning (loss of
            # per-resource ordering). Surface it rather than silently
            # round-robining the record.
            self.metrics.empty_partition_keys += 1
            _LOG.warning(
                "pantheon_empty_partition_key",
                extra={"topic": topic, "principal": principal},
            )
        return await self.provider.publish(topic, key, enriched)

    # ---- consumer loop -------------------------------------------------

    async def run(self) -> None:
        """Start one background task per (topic, subscriber) pair.

        Each subscriber uses a distinct consumer group so multiple
        pantheon agents can consume the same topic without stealing each
        other's records (Kafka semantics: same group = load-balance;
        distinct group = fan-out).

        Blast-radius isolation: consumers are gathered with
        ``return_exceptions=True`` so a single crashed consumer never
        cancels its siblings. Each crash is counted and logged in
        :meth:`_consume`; this method surfaces only a summary.
        """
        if self._tasks:
            raise RuntimeError("EventBusBridge.run() is already running; call stop() first")
        for topic, subs in self._subs.items():
            for agent_name, handler in subs:
                group_id = f"{self.consumer_group_prefix}.{agent_name}"
                task = asyncio.create_task(
                    self._consume(topic=topic, group_id=group_id, handler=handler),
                    name=f"pantheon-consumer.{agent_name}.{topic}",
                )
                self._tasks.append(task)
        self.metrics.consumers_started = len(self._tasks)
        if not self._tasks:
            _LOG.info("pantheon_bridge_no_subscribers")
            return
        _LOG.info(
            "pantheon_bridge_started",
            extra={"consumers": len(self._tasks), "prefix": self.consumer_group_prefix},
        )
        try:
            results = await asyncio.gather(*self._tasks, return_exceptions=True)
            crashed = 0
            for task, result in zip(self._tasks, results, strict=True):
                if isinstance(result, BaseException) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    crashed += 1
                    # Log each crashing consumer distinctly so an operator
                    # can identify *which* topic wedged. A bare aggregate
                    # count buries the root cause under a summary.
                    _LOG.error(
                        "pantheon_bridge_consumer_crashed",
                        extra={
                            "task_name": task.get_name(),
                            "error_type": type(result).__name__,
                            "error": str(result),
                        },
                    )
            if crashed:
                _LOG.error(
                    "pantheon_bridge_consumers_crashed",
                    extra={"crashed": crashed, "total": len(results)},
                )
        finally:
            # Ensure no orphan tasks remain even if one crashes.
            await self.stop()

    async def stop(self) -> None:
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            # Bounded drain: a wedged consumer (e.g. a handler stuck in a
            # non-cancellable blocking call) MUST NOT hang process
            # shutdown. Cancelled tasks that do not settle within the
            # timeout are abandoned; they are already cancel-requested.
            await asyncio.wait(self._tasks, timeout=self.shutdown_timeout)
        self._tasks.clear()

    async def _consume(
        self,
        *,
        topic: str,
        group_id: str,
        handler: Handler,
    ) -> None:
        # Self-healing: a subscribe-loop crash restarts THIS consumer with
        # exponential backoff (blast-radius isolation keeps siblings
        # running; self-healing brings a crashed subscription back rather
        # than leaving it permanently dead). After max_consumer_restarts
        # the consumer gives up - counted + logged - without touching the
        # rest of the pantheon.
        attempt = 0
        while True:
            try:
                async for envelope in self.provider.subscribe(topic, group_id):
                    try:
                        await handler(topic, dict(envelope.payload))
                        self.metrics.delivered += 1
                        attempt = 0  # progress resets the backoff window
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - route to DLQ, keep loop alive
                        self.metrics.handler_errors += 1
                        _LOG.warning(
                            "pantheon_handler_error",
                            extra={
                                "group_id": group_id,
                                "topic": topic,
                                "offset": envelope.offset,
                                "error": str(exc),
                            },
                        )
                        await self._safe_dead_letter(
                            group_id=group_id, topic=topic, envelope=envelope, exc=exc
                        )
                # Iterator ended normally (finite in-memory drain): done.
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                self.metrics.consumers_crashed += 1
                attempt += 1
                if attempt > self.max_consumer_restarts:
                    self.metrics.consumers_gave_up += 1
                    _LOG.exception(
                        "pantheon_consumer_gave_up",
                        extra={
                            "group_id": group_id,
                            "topic": topic,
                            "attempts": attempt,
                        },
                    )
                    return
                backoff = min(
                    self.restart_backoff_base * (2 ** (attempt - 1)),
                    self.restart_backoff_max,
                )
                # Full jitter (AWS-style): spread simultaneous restarts so a
                # broker outage that crashes many consumers at once does not
                # produce a synchronized retry storm on recovery. Jitter is
                # non-security (retry timing, not entropy), so ``random`` is
                # fine.
                backoff = random.uniform(0.0, backoff)  # noqa: S311 - retry jitter, not crypto
                self.metrics.consumers_restarted += 1
                _LOG.warning(
                    "pantheon_consumer_restarting",
                    extra={
                        "group_id": group_id,
                        "topic": topic,
                        "attempt": attempt,
                        "backoff_s": backoff,
                    },
                )
                await asyncio.sleep(backoff)
                # loop: re-subscribe, resuming from the committed offset.

    async def _safe_dead_letter(
        self,
        *,
        group_id: str,
        topic: str,
        envelope: Any,
        exc: Exception,
    ) -> None:
        """Route a poison record to the DLQ, isolating DLQ failures.

        A broker hiccup on the DLQ path MUST NOT crash the consumer (that
        would turn one bad record into a dead subscription); it is
        counted and logged instead.
        """
        try:
            await self.provider.dead_letter(
                topic,
                envelope.key,
                envelope.payload,
                reason=f"handler error: {exc}",
            )
            self.metrics.dead_lettered += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            self.metrics.dead_letter_errors += 1
            _LOG.exception(
                "pantheon_dead_letter_failed",
                extra={"group_id": group_id, "topic": topic},
            )


__all__ = ["EventBusBridge", "BridgeMetrics"]
