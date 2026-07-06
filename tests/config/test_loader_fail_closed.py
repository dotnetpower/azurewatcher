"""Fail-fast behaviour of the config loader.

Every missing / invalid input MUST be reported through a single
:class:`ConfigError` with a full issue list. Partial success is prohibited.
"""

from __future__ import annotations

import pytest

from aiopspilot.shared.config import (
    AppConfig,
    ConfigError,
    RuntimeConfig,
    load_from_mapping,
)
from aiopspilot.shared.contracts.models import Mode

# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_full_config_passes() -> None:
    raw = {
        "schema_version": "1.0.0",
        "azure": {
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "region": "krc",
        },
        "kafka": {
            "bootstrap_servers": "evhns-aiopspilot.example.local:9093",
            "topic_events": "aw.change.events",
        },
        "postgres": {"host": "psql-aiopspilot.example.local", "database": "aiopspilot"},
        "runtime": {"env": "dev"},
    }
    cfg = load_from_mapping(raw)
    assert isinstance(cfg, AppConfig)
    # Default RG name from the CAF convention is applied automatically.
    assert cfg.azure.resource_group == "rg-aiopspilot"
    # Autonomy default MUST land on shadow - safety invariant.
    assert cfg.runtime.autonomy_mode_default is Mode.SHADOW
    # Rule catalog default ref is present.
    assert cfg.rule_catalog.ref == "main"


def test_default_rule_catalog_ref_applied_when_omitted() -> None:
    raw = _minimal_raw()
    cfg = load_from_mapping(raw)
    assert cfg.rule_catalog.ref == "main"


def test_shadow_default_survives_when_field_omitted() -> None:
    raw = _minimal_raw()
    # Do NOT set runtime.autonomy_mode_default; MUST default to shadow.
    cfg = load_from_mapping(raw)
    assert cfg.runtime.autonomy_mode_default is Mode.SHADOW


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------


def test_missing_multiple_required_fields_lists_all_in_one_error() -> None:
    """The whole missing-field list is surfaced in one shot."""
    raw = {
        "schema_version": "1.0.0",
        "azure": {},
        "kafka": {},
        "postgres": {},
        "runtime": {},
    }
    with pytest.raises(ConfigError) as exc:
        load_from_mapping(raw)

    keys = {i.key for i in exc.value.issues}
    # every required sub-field should appear in the aggregated error
    for expected in {"azure", "kafka", "postgres", "runtime"}:
        assert any(k.startswith(expected) or k == expected for k in keys), (
            f"missing {expected} not reported: {keys}"
        )
    # And more than one issue was gathered before raising.
    assert len(exc.value.issues) >= 4


def test_invalid_autonomy_mode_default_is_rejected() -> None:
    raw = _minimal_raw()
    raw["runtime"]["autonomy_mode_default"] = "exec"  # wrong value
    with pytest.raises(ConfigError) as exc:
        load_from_mapping(raw)
    assert any("autonomy_mode_default" in i.key for i in exc.value.issues)


def test_invalid_runtime_env_is_rejected() -> None:
    raw = _minimal_raw()
    raw["runtime"]["env"] = "development"  # only dev/staging/prod
    with pytest.raises(ConfigError) as exc:
        load_from_mapping(raw)
    assert any(i.key.endswith("env") for i in exc.value.issues)


def test_extra_field_at_root_is_rejected() -> None:
    """Additional properties at the boundary are a config drift signal."""
    raw = _minimal_raw()
    raw["random_key"] = "should_be_rejected"
    with pytest.raises(ConfigError):
        load_from_mapping(raw)


def test_bad_semver_is_rejected() -> None:
    raw = _minimal_raw()
    raw["schema_version"] = "1.x"
    with pytest.raises(ConfigError) as exc:
        load_from_mapping(raw)
    assert any(i.key == "schema_version" for i in exc.value.issues)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_raw() -> dict[str, dict[str, str] | str]:
    return {
        "schema_version": "1.0.0",
        "azure": {
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "region": "krc",
        },
        "kafka": {
            "bootstrap_servers": "evhns-aiopspilot.example.local:9093",
            "topic_events": "aw.change.events",
        },
        "postgres": {"host": "psql-aiopspilot.example.local", "database": "aiopspilot"},
        "runtime": {"env": "dev"},
    }


def test_runtime_config_can_be_constructed_in_code() -> None:
    """Nothing in the model surface forces the user through ``load_from_mapping``."""
    rt = RuntimeConfig(env="dev", autonomy_mode_default=Mode.SHADOW)
    assert rt.env == "dev"
    assert rt.autonomy_mode_default is Mode.SHADOW
