"""Fault-injection harness - governed, reversible chaos experiments.

The harness runs a :class:`FaultScenario` against a set of
**already-approved** targets and returns an audit-shaped
:class:`ExperimentResult`. It enforces all four safety invariants:

- Shadow is the default and **never** touches an injector (shadow never
  mutates); it records intent and returns ``SHADOWED``.
- Enforce injects, holds for the bounded duration, probes for the expected
  detection signal, and **always** stops/rolls back in a ``finally`` block.
- Blast-radius is capped per scenario before any injection.
- Every run is recorded through the :class:`ExperimentRecorder` audit sink.

Enforce mode presupposes upstream HIL approval (Loki proposes -> Forseti
judges -> Var approves); the harness is the executor of an already-approved
experiment, never the approver.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from fdai.core.chaos.contract import ExperimentOutcome, ExperimentResult, FaultScenario
from fdai.core.chaos.injector import (
    ExperimentRecorder,
    FaultInjector,
    InMemoryExperimentRecorder,
    NoSignalProbe,
    SignalProbe,
)
from fdai.shared.contracts.models import Mode

_LOGGER = logging.getLogger(__name__)

_WILDCARD = "*"


class FaultInjectionHarness:
    """Run governed, reversible fault-injection experiments."""

    __slots__ = ("_injectors", "_probe", "_recorder", "_sleeper", "_wall_clock")

    def __init__(
        self,
        *,
        injectors: Sequence[FaultInjector] = (),
        probe: SignalProbe | None = None,
        recorder: ExperimentRecorder | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._injectors: dict[str, FaultInjector] = {inj.fault_type: inj for inj in injectors}
        self._probe: SignalProbe = probe or NoSignalProbe()
        self._recorder: ExperimentRecorder = recorder or InMemoryExperimentRecorder()
        self._sleeper: Callable[[float], Awaitable[None]] = sleeper or asyncio.sleep
        self._wall_clock: Callable[[], datetime] = wall_clock or (lambda: datetime.now(tz=UTC))

    def _resolve(self, fault_type: str) -> FaultInjector | None:
        return self._injectors.get(fault_type) or self._injectors.get(_WILDCARD)

    async def run(
        self,
        scenario: FaultScenario,
        *,
        approved_targets: Sequence[str],
        mode: Mode = Mode.SHADOW,
    ) -> ExperimentResult:
        started = self._wall_clock()
        experiment_id = f"chaos-{uuid4().hex[:12]}"
        targets = tuple(approved_targets)

        # Blast-radius gate - refuse before any perturbation.
        if len(targets) > scenario.blast_radius_cap:
            return await self._finish(
                experiment_id=experiment_id,
                scenario=scenario,
                mode=mode,
                targets=targets,
                started=started,
                outcome=ExperimentOutcome.BLAST_RADIUS_EXCEEDED,
                detected=False,
                injected=False,
                stopped=False,
                error=(f"approved_targets={len(targets)} exceeds cap={scenario.blast_radius_cap}"),
            )

        # Shadow never touches an injector - judge and log only.
        if mode is Mode.SHADOW:
            return await self._finish(
                experiment_id=experiment_id,
                scenario=scenario,
                mode=mode,
                targets=targets,
                started=started,
                outcome=ExperimentOutcome.SHADOWED,
                detected=False,
                injected=False,
                stopped=False,
            )

        injector = self._resolve(scenario.fault_type)
        if injector is None:
            return await self._finish(
                experiment_id=experiment_id,
                scenario=scenario,
                mode=mode,
                targets=targets,
                started=started,
                outcome=ExperimentOutcome.ABORTED,
                detected=False,
                injected=False,
                stopped=False,
                error=f"no_injector_for_fault_type:{scenario.fault_type}",
            )

        injected_targets: list[str] = []
        detected = False
        error: str | None = None
        try:
            for target in targets:
                await injector.inject(target=target, params=scenario.params)
                injected_targets.append(target)
            await self._sleeper(scenario.duration_seconds)
            detected = await self._probe.observed(signal=scenario.expected_signal, targets=targets)
        except Exception as exc:  # noqa: BLE001 - fail closed, always roll back
            error = f"{type(exc).__name__}:{exc}"
            _LOGGER.error(
                "chaos_experiment_failed",
                extra={"experiment_id": experiment_id, "scenario": scenario.scenario_id},
            )
        finally:
            # Always roll back every target that was actually injected, even
            # on a partial injection (target 1 ok, target 2 raised) - leaving a
            # live fault would violate the always-rollback safety invariant.
            stopped = True
            if injected_targets:
                stopped = await self._stop_all(injector, injected_targets)

        injected = bool(injected_targets)
        if error is not None:
            outcome = ExperimentOutcome.ABORTED
        elif detected:
            outcome = ExperimentOutcome.VALIDATED
        else:
            outcome = ExperimentOutcome.NOT_DETECTED

        return await self._finish(
            experiment_id=experiment_id,
            scenario=scenario,
            mode=mode,
            targets=targets,
            started=started,
            outcome=outcome,
            detected=detected,
            injected=injected,
            stopped=stopped,
            error=error,
        )

    async def _stop_all(self, injector: FaultInjector, targets: Sequence[str]) -> bool:
        """Stop every target; report whether rollback fully succeeded."""
        ok = True
        for target in targets:
            try:
                await injector.stop(target=target)
            except Exception:  # noqa: BLE001 - rollback failure must be recorded, not raised
                ok = False
                _LOGGER.error("chaos_rollback_failed", extra={"target": target})
        return ok

    async def _finish(
        self,
        *,
        experiment_id: str,
        scenario: FaultScenario,
        mode: Mode,
        targets: tuple[str, ...],
        started: datetime,
        outcome: ExperimentOutcome,
        detected: bool,
        injected: bool,
        stopped: bool,
        error: str | None = None,
    ) -> ExperimentResult:
        result = ExperimentResult(
            experiment_id=experiment_id,
            scenario_id=scenario.scenario_id,
            mode=mode,
            targets=targets,
            outcome=outcome,
            expected_signal=scenario.expected_signal,
            detected=detected,
            started_at=started,
            ended_at=self._wall_clock(),
            injected=injected,
            stopped=stopped,
            error=error,
        )
        try:
            await self._recorder.record(result)
        except Exception:  # noqa: BLE001 - audit sink failure must not mask the result
            _LOGGER.error("chaos_audit_record_failed", extra={"id": experiment_id})
        return result


__all__ = ["FaultInjectionHarness"]
