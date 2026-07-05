"""EnvVarConfigProvider — the upstream default :class:`ConfigProvider`.

Also verifies the DI contract: the same behaviour observed via
:class:`EnvVarConfigProvider` MUST be reproducible by any fake that
satisfies the :class:`ConfigProvider` Protocol. That is the DI evidence.
"""

from __future__ import annotations

import pytest

from aiopspilot.shared.config import AppConfig, ConfigError, ConfigProvider
from aiopspilot.shared.config.provider import EnvVarConfigProvider

VALID_ENV: dict[str, str] = {
    "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000000",
    "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
    "AZURE_REGION": "krc",
    "KAFKA_BOOTSTRAP_SERVERS": "evhns-aiopspilot.example.local:9093",
    "KAFKA_TOPIC_EVENTS": "aw.change.events",
    "POSTGRES_HOST": "psql-aiopspilot.example.local",
    "POSTGRES_DATABASE": "aiopspilot",
    "RUNTIME_ENV": "dev",
}


def test_env_provider_reads_valid_env() -> None:
    cfg = EnvVarConfigProvider(env=VALID_ENV).get()
    assert isinstance(cfg, AppConfig)
    assert cfg.azure.region == "krc"
    assert cfg.kafka.topic_events == "aw.change.events"
    # Default RG is applied even when the env var is omitted.
    assert cfg.azure.resource_group == "rg-aiopspilot"


def test_env_provider_reports_all_missing_at_once() -> None:
    provider = EnvVarConfigProvider(env={})
    with pytest.raises(ConfigError) as exc:
        provider.get()
    # Every required env var is in the issue list.
    reported = {i.key for i in exc.value.issues}
    for k in (
        "AZURE_TENANT_ID",
        "AZURE_SUBSCRIPTION_ID",
        "AZURE_REGION",
        "KAFKA_BOOTSTRAP_SERVERS",
        "KAFKA_TOPIC_EVENTS",
        "POSTGRES_HOST",
        "POSTGRES_DATABASE",
        "RUNTIME_ENV",
    ):
        assert k in reported, f"{k} not reported: {reported}"


def test_env_provider_rejects_invalid_enum_value() -> None:
    bad_env = dict(VALID_ENV)
    bad_env["AUTONOMY_MODE_DEFAULT"] = "exec"
    with pytest.raises(ConfigError) as exc:
        EnvVarConfigProvider(env=bad_env).get()
    assert any("autonomy_mode_default" in i.key for i in exc.value.issues)


# ---------------------------------------------------------------------------
# DI evidence: swap the ConfigProvider, downstream behaviour unchanged.
# ---------------------------------------------------------------------------


class _InMemoryConfigProvider:
    """Test-only ``ConfigProvider`` — hands back a preassembled AppConfig."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def get(self) -> AppConfig:
        return self._cfg


def test_in_memory_provider_satisfies_the_protocol(app_config: AppConfig) -> None:
    fake: ConfigProvider = _InMemoryConfigProvider(app_config)
    got = fake.get()
    assert isinstance(got, AppConfig)
    assert got is app_config


def test_env_and_in_memory_providers_produce_equivalent_shapes(
    app_config: AppConfig,
) -> None:
    """Two providers, one Protocol: consumers cannot tell them apart."""
    from_env = EnvVarConfigProvider(env=VALID_ENV).get()
    from_fake = _InMemoryConfigProvider(app_config).get()

    # Same structural shape — every top-level section present in both.
    assert set(from_env.model_dump().keys()) == set(from_fake.model_dump().keys())
    # Same safety default for autonomy mode.
    assert from_env.runtime.autonomy_mode_default == from_fake.runtime.autonomy_mode_default
