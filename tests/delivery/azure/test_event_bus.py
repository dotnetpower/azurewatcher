"""EventHubsKafkaBus — construction + close guards.

Full round-trip against Event Hubs requires a live broker (or an
aiokafka-compatible mock like ``redpanda`` in dev-up.sh); those cases
are covered by the persistence-style integration flow. The tests here
exercise the wire-adapter code paths that do not need a broker:

- construction guards on config values,
- the encoder/decoder helpers used by every message,
- token-provider bridging into aiokafka's async contract,
- ``close()`` idempotency.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from aiopspilot.delivery.azure.event_bus import (
    EventHubsKafkaBus,
    EventHubsKafkaBusConfig,
    _decode,  # type: ignore[attr-defined]
    _decode_key,  # type: ignore[attr-defined]
    _encode,  # type: ignore[attr-defined]
    _EntraTokenProvider,  # type: ignore[attr-defined]
)
from aiopspilot.shared.providers.workload_identity import IdentityToken, WorkloadIdentity


class _StaticIdentity(WorkloadIdentity):
    def __init__(self, token: str = "fake-token") -> None:  # noqa: S107 — synthetic test fixture
        self._token = token
        self.calls: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.calls.append(audience)
        return IdentityToken(
            token=self._token,
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            audience=audience,
        )


def _cfg(**overrides: object) -> EventHubsKafkaBusConfig:
    base: dict[str, object] = {"bootstrap_servers": "evhns.servicebus.windows.net:9093"}
    base.update(overrides)
    return EventHubsKafkaBusConfig(**base)  # type: ignore[arg-type]


def test_construction_rejects_empty_bootstrap_servers() -> None:
    with pytest.raises(ValueError, match="bootstrap_servers"):
        EventHubsKafkaBus(identity=_StaticIdentity(), config=_cfg(bootstrap_servers=""))


def test_encode_produces_deterministic_bytes() -> None:
    payload = {"b": 2, "a": 1}
    encoded = _encode(payload)
    assert encoded == b'{"a":1,"b":2}'
    # And matches after a round-trip through json.
    assert json.loads(encoded) == {"a": 1, "b": 2}


def test_decode_returns_empty_dict_for_none() -> None:
    assert _decode(None) == {}


def test_decode_wraps_non_dict_payload() -> None:
    assert _decode(b'"just-a-string"') == {"_wrapped": "just-a-string"}


def test_decode_raw_fallback_on_bad_json() -> None:
    result = _decode(b"not-json{")
    assert "_raw" in result


def test_decode_key_utf8() -> None:
    assert _decode_key(b"resource:example/rg/x") == "resource:example/rg/x"
    assert _decode_key(None) == ""


@pytest.mark.asyncio
async def test_entra_token_provider_delegates_to_workload_identity() -> None:
    identity = _StaticIdentity(token="entra-token-abc")
    provider = _EntraTokenProvider(identity)
    token = await provider.token()
    assert token == "entra-token-abc"
    # Audience MUST be the Event Hubs OIDC scope so the broker accepts it.
    assert identity.calls == ["https://eventhubs.azure.net/.default"]


@pytest.mark.asyncio
async def test_close_is_idempotent_before_start() -> None:
    bus = EventHubsKafkaBus(identity=_StaticIdentity(), config=_cfg())
    # Never started a producer — close MUST not raise.
    await bus.close()
    await bus.close()
