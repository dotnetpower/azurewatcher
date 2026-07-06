"""EventIngest - normalize + deduplicate boundary."""

from __future__ import annotations

from typing import Any

import pytest

from aiopspilot.core.event_ingest import EventIngest
from aiopspilot.shared.contracts.models import Event, Mode
from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry
from aiopspilot.shared.contracts.validation import (
    ContractValidationError,
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)


def _validator() -> JsonSchemaEventValidator:
    return JsonSchemaEventValidator(JsonSchemaContractValidator(PackageResourceSchemaRegistry()))


def test_ingest_accepts_valid_event(valid_event: dict[str, Any]) -> None:
    ingest = EventIngest(validator=_validator())
    got = ingest.ingest(valid_event)
    assert isinstance(got, Event)
    assert got.event_id.hex == valid_event["event_id"].replace("-", "")
    assert got.mode is Mode.SHADOW


def test_ingest_accepts_pre_validated_event_instance(
    valid_event: dict[str, Any],
) -> None:
    """A caller that already holds an ``Event`` (e.g. an in-process
    replay) MUST NOT be forced to serialize back to a dict."""
    event = Event.model_validate(valid_event)
    ingest = EventIngest(validator=_validator())
    assert ingest.ingest(event) is event


def test_duplicate_idempotency_key_returns_none(valid_event: dict[str, Any]) -> None:
    ingest = EventIngest(validator=_validator())
    assert ingest.ingest(valid_event) is not None
    second = ingest.ingest(valid_event)
    assert second is None


def test_seen_keys_tracks_processed(valid_event: dict[str, Any]) -> None:
    ingest = EventIngest(validator=_validator())
    ingest.ingest(valid_event)
    assert valid_event["idempotency_key"] in ingest.seen_keys()


def test_schema_invalid_raises_contract_error(valid_event: dict[str, Any]) -> None:
    ingest = EventIngest(validator=_validator())
    del valid_event["event_id"]
    with pytest.raises(ContractValidationError):
        ingest.ingest(valid_event)


def test_two_distinct_events_both_pass(valid_event: dict[str, Any]) -> None:
    ingest = EventIngest(validator=_validator())
    first = ingest.ingest(valid_event)
    second_raw = {
        **valid_event,
        "event_id": "00000000-0000-0000-0000-000000000099",
        "idempotency_key": "another-key",
    }
    second = ingest.ingest(second_raw)
    assert first is not None
    assert second is not None
    assert ingest.seen_keys() == {
        valid_event["idempotency_key"],
        "another-key",
    }
