"""Coverage tests for the SRE demo scenario pack.

Ensures :func:`default_scenarios` covers every S/C fault scenario in
``docs/internals/sre-demo-scenarios-08-fdai-coverage.md`` (S13 / S14 are
non-fault and excluded here) with the canonical ``expected_signal`` from
:mod:`fdai.core.detection.signals`. If a scenario is removed or its
``expected_signal`` drifts, these tests fail before any doc drifts.
"""

from __future__ import annotations

from fdai.core.chaos import (
    AKS_BAD_DEPLOY,
    AKS_HTTP_ABORT,
    AKS_POD_CPU_SPIKE,
    AKS_POD_KILL,
    AOAI_TPM_THROTTLE,
    APPGW_BACKEND_FAILURE,
    MYSQL_CPU_PRESSURE,
    NETWORK_RTT_DELAY,
    VM_CPU_STRESS,
    VM_MEM_STRESS,
    default_scenarios,
)
from fdai.core.detection.signals import (
    SIGNAL_BACKEND_HEALTH,
    SIGNAL_DB_CPU,
    SIGNAL_GATEWAY_LATENCY,
    SIGNAL_HOST_CPU,
    SIGNAL_HOST_MEMORY,
    SIGNAL_NODE_CPU,
    SIGNAL_POD_RESTART,
    SIGNAL_RATE_LIMIT,
    SIGNAL_REQUEST_FAILURE,
    SIGNAL_ROLLOUT_STALL,
    is_known_signal,
)

# One row per S/C scenario the coverage matrix promises will fire.
# (scenario, expected_signal). New rows added here must have a
# corresponding FaultScenario in ``default_scenarios``.
_COVERAGE = (
    (AKS_POD_KILL, SIGNAL_POD_RESTART),                # S1, C2
    (AKS_POD_CPU_SPIKE, SIGNAL_NODE_CPU),              # S2, C3
    (NETWORK_RTT_DELAY, SIGNAL_GATEWAY_LATENCY),       # S3, S7, S10
    (AKS_HTTP_ABORT, SIGNAL_REQUEST_FAILURE),          # S4
    (VM_CPU_STRESS, SIGNAL_HOST_CPU),                  # S5
    (VM_MEM_STRESS, SIGNAL_HOST_MEMORY),               # S6, C4
    (MYSQL_CPU_PRESSURE, SIGNAL_DB_CPU),               # S8
    (AOAI_TPM_THROTTLE, SIGNAL_RATE_LIMIT),            # S9
    (APPGW_BACKEND_FAILURE, SIGNAL_BACKEND_HEALTH),    # S11
    (AKS_BAD_DEPLOY, SIGNAL_ROLLOUT_STALL),            # S12
)

# The demo's 5-minute alert window plus one probe cycle. Any scenario
# with a shorter hold could VALIDATE too early to model the demo.
_MIN_HOLD_SECONDS = 360.0


def test_every_covered_scenario_uses_expected_signal() -> None:
    """The coverage-matrix expected_signal ↔ scenario mapping is exact."""
    for scenario, expected in _COVERAGE:
        assert scenario.expected_signal == expected, (
            f"{scenario.scenario_id}: expected_signal drifted "
            f"({scenario.expected_signal!r} vs {expected!r})"
        )


def test_every_covered_scenario_signal_is_registered() -> None:
    """Each scenario's expected_signal is in the canonical registry."""
    for scenario, _expected in _COVERAGE:
        assert is_known_signal(scenario.expected_signal), (
            f"{scenario.scenario_id} expected_signal "
            f"{scenario.expected_signal!r} is not registered in "
            f"fdai.core.detection.signals"
        )


def test_default_scenarios_covers_full_matrix() -> None:
    """default_scenarios returns exactly the set the matrix promises."""
    got = {s.scenario_id for s in default_scenarios()}
    want = {s.scenario_id for s, _ in _COVERAGE}
    assert got == want, f"scenario mismatch: extra={got - want}, missing={want - got}"


def test_scenario_ids_are_unique() -> None:
    """No accidental duplicate scenario id (would break audit lookup)."""
    ids = [s.scenario_id for s in default_scenarios()]
    assert len(ids) == len(set(ids)), f"duplicate scenario ids: {ids}"


def test_every_scenario_holds_through_the_alert_window() -> None:
    """duration_seconds >= 5-min alert window + 1 probe cycle."""
    for scenario in default_scenarios():
        assert scenario.duration_seconds >= _MIN_HOLD_SECONDS, (
            f"{scenario.scenario_id}: duration {scenario.duration_seconds}s "
            f"is under the {_MIN_HOLD_SECONDS}s alert-window minimum"
        )


def test_every_scenario_has_rollback_note() -> None:
    """Rollback path is documented for every governed experiment."""
    for scenario in default_scenarios():
        assert scenario.rollback_note.strip(), (
            f"{scenario.scenario_id}: rollback_note MUST be non-empty"
        )
