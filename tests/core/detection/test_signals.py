"""Detection-signal registry tests.

The signal registry is the shared vocabulary the detection layer, the
trust router, the investigation analyzers, and the chaos harness use to
name one observable condition. It MUST stay stable (constant values are
audit and config surface) and internally consistent.
"""

from __future__ import annotations

from fdai.core.detection.signals import (
    SIGNAL_BACKEND_HEALTH,
    SIGNAL_DB_CPU,
    SIGNAL_GATEWAY_LATENCY,
    SIGNAL_HOST_CPU,
    SIGNAL_HOST_MEMORY,
    SIGNAL_MEMBER_HOTSPOT,
    SIGNAL_NODE_CPU,
    SIGNAL_POD_RESTART,
    SIGNAL_RATE_LIMIT,
    SIGNAL_REQUEST_FAILURE,
    SIGNAL_ROLLOUT_STALL,
    SignalSpec,
    is_known_signal,
    known_signals,
)

_ALL_CONSTANTS = (
    SIGNAL_BACKEND_HEALTH,
    SIGNAL_DB_CPU,
    SIGNAL_GATEWAY_LATENCY,
    SIGNAL_HOST_CPU,
    SIGNAL_HOST_MEMORY,
    SIGNAL_MEMBER_HOTSPOT,
    SIGNAL_NODE_CPU,
    SIGNAL_POD_RESTART,
    SIGNAL_RATE_LIMIT,
    SIGNAL_REQUEST_FAILURE,
    SIGNAL_ROLLOUT_STALL,
)


def test_every_constant_is_registered() -> None:
    for name in _ALL_CONSTANTS:
        assert is_known_signal(name), f"constant {name!r} missing from registry"


def test_registry_keys_match_specs() -> None:
    for key, spec in known_signals().items():
        assert isinstance(spec, SignalSpec)
        assert key == spec.signal, "registry key must equal SignalSpec.signal"


def test_registry_is_read_only() -> None:
    registry = known_signals()
    try:
        registry["injected_signal"] = SignalSpec(  # type: ignore[index]
            signal="injected_signal",
            description="d",
            tier_hint="T0",
            rca_hint="r",
        )
    except TypeError:
        return
    raise AssertionError("known_signals() must return a read-only mapping")


def test_tier_hint_is_recognized() -> None:
    """Tier hints stay within the known routing shapes."""
    allowed = {"T0", "T0+T1", "T0+T2", "T0+forecast"}
    for spec in known_signals().values():
        assert spec.tier_hint in allowed, (
            f"{spec.signal}: unknown tier_hint {spec.tier_hint!r}"
        )


def test_unknown_signal_is_rejected() -> None:
    assert not is_known_signal("nope_not_here")
