"""Chaos / fault-injection harness (SRE-agent slide 9).

A governed, reversible fault-injection surface that validates the
detect -> mitigate loop. Shadow is the default and never perturbs anything;
enforce presupposes upstream HIL approval (Loki proposes -> Forseti judges
-> Var approves). Every experiment carries a bounded duration (stop), an
always-called rollback, a per-scenario blast-radius cap, and an audit
record.

Entry points:

- :class:`FaultInjectionHarness` - run an experiment, get an
  :class:`ExperimentResult`.
- :func:`default_scenarios` - the reference catalog mirroring the demo.
- :class:`ShadowFaultInjector` - the safe upstream default injector.
"""

from __future__ import annotations

from fdai.core.chaos.contract import (
    ExperimentOutcome,
    ExperimentResult,
    FaultScenario,
)
from fdai.core.chaos.harness import FaultInjectionHarness
from fdai.core.chaos.injector import (
    ExperimentRecorder,
    FaultInjector,
    InMemoryExperimentRecorder,
    NoSignalProbe,
    ShadowFaultInjector,
    SignalProbe,
)
from fdai.core.chaos.scenarios import (
    AKS_POD_CPU_SPIKE,
    AOAI_TPM_THROTTLE,
    APPGW_BACKEND_FAILURE,
    MYSQL_CPU_PRESSURE,
    NETWORK_RTT_DELAY,
    default_scenarios,
)

__all__ = [
    "AKS_POD_CPU_SPIKE",
    "AOAI_TPM_THROTTLE",
    "APPGW_BACKEND_FAILURE",
    "MYSQL_CPU_PRESSURE",
    "NETWORK_RTT_DELAY",
    "ExperimentOutcome",
    "ExperimentRecorder",
    "ExperimentResult",
    "FaultInjectionHarness",
    "FaultInjector",
    "FaultScenario",
    "InMemoryExperimentRecorder",
    "NoSignalProbe",
    "ShadowFaultInjector",
    "SignalProbe",
    "default_scenarios",
]
