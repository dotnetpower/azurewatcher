"""Chat-based creation commands (SRE-agent slides 15-16).

Two async, RBAC-gated commands that let an operator create records from the
conversational surface, on top of the existing async writers:

- :class:`CreateIncidentCommand` - open an incident record via the
  :class:`~fdai.core.incident.registry.IncidentRegistry` (slide 15). The
  incident is the anchor a Saga handoff turns into a GitHub issue; this
  command creates the record, it does not execute a change.
- :class:`CreateScheduledTaskCommand` - create a recurring monitoring task
  in the shared :class:`~fdai.core.scheduler.store.ScheduleStore` (slide
  16), which the next scheduler tick fires into the control loop.

Both enforce a ``CONTRIBUTOR`` role floor. Neither is an autonomous action:
an incident is a record, and a scheduled task only re-emits a synthetic
event that the trust-router + risk-gate still govern (SchedulerService
defaults to shadow mode).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fdai.core.conversation.session import (
    Principal,
    Role,
    principal_has_role_at_least,
)
from fdai.core.incident.registry import IncidentRegistry
from fdai.core.scheduler.models import ScheduledTask
from fdai.core.scheduler.store import ScheduleStore
from fdai.shared.contracts.models import Incident, IncidentSeverity

_CREATE_FLOOR: Role = Role.CONTRIBUTOR


class CreationForbiddenError(PermissionError):
    """Raised when the principal is below the creation role floor."""


def _require_floor(principal: Principal, action: str) -> None:
    if not principal_has_role_at_least(principal.role, _CREATE_FLOOR):
        raise CreationForbiddenError(
            f"{action} requires role>={_CREATE_FLOOR.value}; principal role={principal.role.value}"
        )


class CreateIncidentCommand:
    """Open an incident from the conversational surface (slide 15)."""

    __slots__ = ("_registry",)

    def __init__(self, *, registry: IncidentRegistry) -> None:
        self._registry = registry

    async def create(
        self,
        *,
        principal: Principal,
        correlation_keys: Iterable[str],
        severity: IncidentSeverity,
        member_event_ids: Iterable[UUID] = (),
    ) -> Incident:
        """Open (or return the existing) incident for the correlation keys.

        Idempotent by correlation-key set - re-running with the same keys
        returns the same deterministic incident, never a duplicate.
        """
        _require_floor(principal, "create_incident")
        keys = tuple(correlation_keys)
        members = tuple(member_event_ids)
        if not members:
            # A manually-opened incident still needs an anchor member event;
            # synthesize a deterministic one from the correlation keys so
            # re-runs do not grow the member set.
            anchor = uuid5(NAMESPACE_URL, "fdai.incident.manual://" + "|".join(sorted(keys)))
            members = (anchor,)
        return await self._registry.open(
            correlation_keys=keys,
            severity=severity,
            member_event_ids=members,
            actor_oid=principal.id,
        )


class CreateScheduledTaskCommand:
    """Create a recurring monitoring task from chat (slide 16)."""

    __slots__ = ("_store",)

    def __init__(self, *, store: ScheduleStore) -> None:
        self._store = store

    async def create(
        self,
        *,
        principal: Principal,
        name: str,
        interval_seconds: float,
        event_type: str,
        resource_ref: str | None = None,
        event_payload: Mapping[str, object] | None = None,
        task_id: str | None = None,
    ) -> ScheduledTask:
        """Create a scheduled task the next scheduler tick will fire."""
        _require_floor(principal, "create_scheduled_task")
        task = ScheduledTask(
            task_id=task_id or f"task-{uuid4().hex[:12]}",
            name=name,
            interval_seconds=interval_seconds,
            event_type=event_type,
            created_by=principal.id,
            event_payload=dict(event_payload or {}),
            resource_ref=resource_ref,
        )
        return await self._store.create(task)


__all__ = [
    "CreateIncidentCommand",
    "CreateScheduledTaskCommand",
    "CreationForbiddenError",
]
