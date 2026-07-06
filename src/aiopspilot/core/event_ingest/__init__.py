"""Bus consumers.

Normalize to the event schema, deduplicate by idempotency key, and correlate
related events into incidents.

P1 W-3 Step 3f scope
--------------------

This module ships the two duties the T0 pipeline needs today:

- **Normalize** - accept a raw payload (already-validated ``Event`` or a
  dict destined for the event schema) and return a typed
  :class:`~aiopspilot.shared.contracts.models.Event` model. Enforcing
  the schema at the ingress boundary is the only place where untrusted
  input meets the type system; downstream code can trust it.
- **Deduplicate** - reject a second delivery of the same
  ``idempotency_key`` by returning :data:`None`. In-process for now -
  a Kafka consumer group + persistent dedupe cache lands with W-4.

Correlation-into-incidents is Phase 2 (T1 similarity work); the seam is
declared here so a follow-up wires it without changing the interface.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiopspilot.shared.contracts.models import Event
from aiopspilot.shared.contracts.validation import EventValidator

__all__ = ["EventIngest"]


class EventIngest:
    """Normalize + deduplicate incoming events.

    Wraps an :class:`EventValidator` (JSON Schema + pydantic) plus a
    dedupe cache keyed on ``idempotency_key``.
    """

    def __init__(self, *, validator: EventValidator) -> None:
        self._validator = validator
        self._seen: set[str] = set()

    def ingest(self, raw: Event | Mapping[str, Any]) -> Event | None:
        """Return a typed :class:`Event` or ``None`` for a duplicate.

        Never raises for a duplicate - a re-delivery is a valid runtime
        state, not an error. Schema-invalid input raises whatever the
        validator raises (typically a schema error propagated up), so
        the caller can audit the failure at the ingress boundary.
        """
        event = _coerce(raw, validator=self._validator)
        key = event.idempotency_key
        if key in self._seen:
            return None
        self._seen.add(key)
        return event

    def seen_keys(self) -> frozenset[str]:
        """Return the set of idempotency keys already processed."""
        return frozenset(self._seen)


def _coerce(raw: Event | Mapping[str, Any], *, validator: EventValidator) -> Event:
    if isinstance(raw, Event):
        return raw
    validator.validate(dict(raw))
    return Event.model_validate(dict(raw))
