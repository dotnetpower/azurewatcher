"""Scheduler service - fires due tasks as synthetic control-loop events.

Mirrors :class:`~fdai.core.slo.runner.SloBurnRunner`: a periodic
``run_once`` cycle driven by an out-of-band trigger (a Container Apps Job /
cron in production). Each due :class:`ScheduledTask` is turned into an
:class:`Event` and published to the event-ingest topic, so the standard
trust-router + risk-gate path governs any resulting action. The scheduler
itself is deterministic-first and never executes a change.

``compute_due`` is a pure, I/O-free function so "which tasks fire at time
T" is exhaustively testable without real time or a broker.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from croniter import croniter

from fdai.core.scheduler.models import ScheduledTask
from fdai.core.scheduler.store import ScheduleStore
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.event_bus import EventBus

_LOGGER = logging.getLogger(__name__)

SCHEDULE_EVENT_TOPIC = "aw.schedule.events"
_SOURCE = "fdai.core.scheduler"


def compute_due(tasks: Sequence[ScheduledTask], *, now: datetime) -> list[ScheduledTask]:
    """Return the subset of ``tasks`` that are due to fire at ``now``.

    A task is due when it is enabled, its ``start_at`` (if any) has passed,
    and either it has never run or at least ``interval_seconds`` have
    elapsed since ``last_run``. Pure and deterministic.
    """
    due: list[ScheduledTask] = []
    for task in tasks:
        if not task.enabled:
            continue
        if task.start_at is not None and now < task.start_at:
            continue
        if task.cron_expression is not None:
            if not croniter.match(task.cron_expression, now):
                continue
            if task.last_run is not None and _minute_bucket(task.last_run) == _minute_bucket(now):
                continue
            due.append(task)
            continue
        if task.last_run is None:
            due.append(task)
            continue
        elapsed = (now - task.last_run).total_seconds()
        if elapsed >= task.interval_seconds:
            due.append(task)
    return due


def _schedule_idempotency_key(task: ScheduledTask, now: datetime) -> str:
    """Stable key per interval bucket so a retried tick does not double-fire."""
    bucket = (
        _minute_bucket(now)
        if task.cron_expression is not None
        else int(now.timestamp() // task.interval_seconds)
    )
    return f"schedule:{task.task_id}:{bucket}"


def _minute_bucket(value: datetime) -> int:
    return int(value.timestamp() // 60)


@dataclass(frozen=True, slots=True)
class SchedulerRunReport:
    """Outcome of one ``run_once`` cycle."""

    fired: int
    publish_errors: tuple[tuple[str, str], ...] = ()
    """``(task_id, short_error)`` for each publish that failed."""


class SchedulerService:
    """Fire due scheduled tasks into the control loop."""

    __slots__ = ("_bus", "_clock", "_mode", "_store", "_topic")

    def __init__(
        self,
        *,
        store: ScheduleStore,
        event_bus: EventBus,
        clock: Callable[[], datetime] | None = None,
        topic: str = SCHEDULE_EVENT_TOPIC,
        mode: Mode = Mode.SHADOW,
    ) -> None:
        self._store = store
        self._bus = event_bus
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(tz=UTC))
        self._topic = topic
        self._mode = mode

    async def run_once(self, *, now: datetime | None = None) -> SchedulerRunReport:
        at = now or self._clock()
        tasks = await self._store.list_all()
        due = compute_due(tasks, now=at)

        fired = 0
        publish_errors: list[tuple[str, str]] = []
        for task in due:
            key = task.resource_ref or task.task_id
            try:
                payload = self._build_payload(task, at)
                await self._bus.publish(self._topic, key, payload)
            except Exception as exc:  # noqa: BLE001 - one bad task must not silence the rest
                publish_errors.append((task.task_id, f"{type(exc).__name__}:{exc}"))
                _LOGGER.warning(
                    "schedule_publish_failed",
                    extra={"task_id": task.task_id, "error": str(exc)},
                )
                continue
            await self._store.mark_run(task.task_id, at)
            fired += 1

        return SchedulerRunReport(fired=fired, publish_errors=tuple(publish_errors))

    def _build_event(self, task: ScheduledTask, at: datetime) -> Event:
        payload = {
            **dict(task.event_payload),
            "scheduled_task": {
                "task_id": task.task_id,
                "name": task.name,
                "created_by": task.created_by,
            },
        }
        return Event(
            schema_version="1.0.0",
            event_id=uuid4(),
            idempotency_key=_schedule_idempotency_key(task, at),
            source=_SOURCE,
            event_type=task.event_type,
            resource_ref=task.resource_ref,
            payload=payload,
            detected_at=at,
            ingested_at=at,
            mode=self._mode,
        )

    def _build_payload(self, task: ScheduledTask, at: datetime) -> dict[str, object]:
        proposal = task.event_payload.get("action_proposal")
        if not isinstance(proposal, dict):
            return self._build_event(task, at).model_dump(mode="json")
        initiator = proposal.get("initiator_principal")
        action_type = proposal.get("action_type")
        params = proposal.get("params")
        if (
            not isinstance(initiator, str)
            or not initiator
            or not isinstance(action_type, str)
            or not action_type
            or not isinstance(params, dict)
        ):
            raise ValueError(f"scheduled task {task.task_id!r} has an invalid action_proposal")
        idempotency_key = _schedule_idempotency_key(task, at)
        return {
            "schema_version": "1.0.0",
            "idempotency_key": idempotency_key,
            "correlation_id": idempotency_key,
            "initiator_principal": initiator,
            "operator_initiated": True,
            "action_type": action_type,
            "resource_id": task.resource_ref,
            "event_type": "operator_request",
            "params": dict(params),
            "scheduled_task": {
                "task_id": task.task_id,
                "name": task.name,
                "created_by": task.created_by,
            },
        }


__all__ = [
    "SCHEDULE_EVENT_TOPIC",
    "SchedulerRunReport",
    "SchedulerService",
    "compute_due",
]
