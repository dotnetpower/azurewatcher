"""Verified audit outcome parsing for pattern growth."""

from __future__ import annotations

from fdai.delivery.measurement.postgres_growth import _outcome_record


def _entry() -> dict[str, object]:
    return {
        "action_id": "action-1",
        "action_type_id": "remediate.tag-add",
        "observed_at": "2026-07-15T00:00:00Z",
        "execution_mode": "enforce",
        "verification_passed": True,
        "decision": "auto",
        "rollback_succeeded": False,
    }


def test_verified_enforce_auto_outcome_is_eligible() -> None:
    record = _outcome_record(_entry())
    assert record is not None
    assert record.was_auto is True
    assert record.was_verified is True
    assert record.was_rolled_back is False


def test_missing_verification_is_not_inferred() -> None:
    entry = _entry()
    entry.pop("verification_passed")
    assert _outcome_record(entry) is None


def test_shadow_execution_is_not_training_data() -> None:
    entry = _entry()
    entry["execution_mode"] = "shadow"
    assert _outcome_record(entry) is None


def test_rollback_is_recorded_as_adverse() -> None:
    entry = _entry()
    entry["rollback_succeeded"] = True
    record = _outcome_record(entry)
    assert record is not None
    assert record.was_rolled_back is True
