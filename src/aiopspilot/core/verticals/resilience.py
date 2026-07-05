"""DR / Chaos scheduler — window-based test failover + measured RPO/RTO.

Phase 3 § DR / Chaos (see
[`docs/roadmap/phases/phase-3-integrated-loop.md § DR / Chaos`]).

Contract
--------

Given a scheduled :class:`DrExperiment` and the current wall-clock time,
the scheduler decides whether the experiment MAY run right now. A run
requires **all** of:

- current time falls inside an approved :class:`MaintenanceWindow`;
- current time is NOT inside a :class:`FreezePeriod`;
- the target resource does NOT carry an ``opt-out`` tag;
- the count of concurrent in-flight experiments stays under
  :attr:`DrSchedulerConfig.max_concurrent_experiments`.

The scheduler is a **pure function of its explicit inputs** — no state
mutation, no audit write, and no I/O. ``at`` MAY be omitted, in which
case the scheduler reads :func:`datetime.now(tz=UTC)` as a convenience
default so callers can fire-and-forget in production; every test in
this module supplies ``at`` explicitly so the outcome is deterministic
regardless of wall-clock. The caller (a P3 orchestrator) persists the
decision + mutates the in-flight count around the actual run.

RPO/RTO measurement
-------------------

:class:`DrRunReport` carries the **measured** RPO (data loss at failover
in seconds) and RTO (wall-clock from trigger to verified restored
service). The scheduler doesn't run experiments; it only decides *when*
they may run. Measurement is produced by the DR runner (owner: DR/Chaos
lead in [phase-3 § Open Questions]) and handed here for reporting.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from statistics import median
from typing import Final


class SchedulerOutcome(StrEnum):
    """One decision from :meth:`DrScheduler.decide`."""

    ALLOWED = "allowed"
    """Experiment MAY run now — window + freeze + tags + concurrency all clear."""

    OUTSIDE_WINDOW = "outside_window"
    """No approved maintenance window is active at the given time."""

    FROZEN = "frozen"
    """A freeze/quiet period overrides any window in effect."""

    OPT_OUT = "opt_out"
    """The target resource is tagged out of chaos runs."""

    CONCURRENCY_CAP = "concurrency_cap"
    """Too many experiments already in flight."""


@dataclass(frozen=True, slots=True)
class MaintenanceWindow:
    """UTC time window during which DR/Chaos runs are allowed.

    Weekly windows are declared by weekday + local-time; the caller
    resolves to UTC before handing to the scheduler.
    """

    name: str
    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment <= self.end


@dataclass(frozen=True, slots=True)
class FreezePeriod:
    """UTC period during which no DR run is permitted (release freeze, holiday, ...)."""

    name: str
    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment <= self.end


@dataclass(frozen=True, slots=True)
class DrExperiment:
    """Descriptor for one scheduled DR / Chaos experiment."""

    experiment_id: str
    target_resource_ref: str
    target_resource_tags: frozenset[str] = field(default_factory=frozenset)
    scheduled_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DrSchedulerConfig:
    """Scheduler policy knobs — every value is auditable config."""

    max_concurrent_experiments: int = 1
    """Cap on in-flight runs. Blast-radius limit on the whole tenant."""

    opt_out_tag: str = "chaos:opt-out"
    """Tag key/value that removes a resource from chaos scope."""


@dataclass(frozen=True, slots=True)
class SchedulerDecision:
    """Frozen record per experiment / moment pair."""

    experiment_id: str
    outcome: SchedulerOutcome
    reasons: tuple[str, ...] = field(default_factory=tuple)
    at: datetime | None = None


class DrScheduler:
    """Pure decision function for DR/Chaos experiments."""

    def __init__(
        self,
        *,
        windows: Iterable[MaintenanceWindow],
        freezes: Iterable[FreezePeriod] = (),
        config: DrSchedulerConfig | None = None,
    ) -> None:
        cfg = config or DrSchedulerConfig()
        if cfg.max_concurrent_experiments < 1:
            raise ValueError("max_concurrent_experiments MUST be >= 1")
        self._windows = tuple(windows)
        self._freezes = tuple(freezes)
        self._config = cfg

    def decide(
        self,
        *,
        experiment: DrExperiment,
        at: datetime | None = None,
        in_flight_experiments: int = 0,
    ) -> SchedulerDecision:
        """Return the scheduler outcome for ``experiment`` at time ``at``."""
        moment = at or datetime.now(tz=UTC)

        # 1. Freeze wins over window (an active freeze blocks any run).
        for freeze in self._freezes:
            if freeze.contains(moment):
                return SchedulerDecision(
                    experiment_id=experiment.experiment_id,
                    outcome=SchedulerOutcome.FROZEN,
                    reasons=(f"freeze:{freeze.name}",),
                    at=moment,
                )

        # 2. Window must be active.
        active = [w for w in self._windows if w.contains(moment)]
        if not active:
            return SchedulerDecision(
                experiment_id=experiment.experiment_id,
                outcome=SchedulerOutcome.OUTSIDE_WINDOW,
                reasons=("no_active_window",),
                at=moment,
            )

        # 3. Opt-out tag on the target resource → skip.
        if self._config.opt_out_tag in experiment.target_resource_tags:
            return SchedulerDecision(
                experiment_id=experiment.experiment_id,
                outcome=SchedulerOutcome.OPT_OUT,
                reasons=(f"opt_out_tag:{self._config.opt_out_tag}",),
                at=moment,
            )

        # 4. Concurrency cap.
        if in_flight_experiments >= self._config.max_concurrent_experiments:
            return SchedulerDecision(
                experiment_id=experiment.experiment_id,
                outcome=SchedulerOutcome.CONCURRENCY_CAP,
                reasons=(
                    f"in_flight={in_flight_experiments}>=cap="
                    f"{self._config.max_concurrent_experiments}",
                ),
                at=moment,
            )

        return SchedulerDecision(
            experiment_id=experiment.experiment_id,
            outcome=SchedulerOutcome.ALLOWED,
            reasons=(f"window:{active[0].name}",),
            at=moment,
        )


# ---------------------------------------------------------------------------
# RPO / RTO measurement + reporting
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DrRunReport:
    """Measured outcome of one completed DR run."""

    experiment_id: str
    completed_at: datetime
    rpo_seconds: float
    """Actual data loss window (older = worse)."""

    rto_seconds: float
    """Wall-clock from failover trigger to verified restored service."""

    integrity_mismatches: int = 0
    smoke_pass: bool = True


_MEDIAN_SENTINEL: Final[float] = -1.0


@dataclass(frozen=True, slots=True)
class DrObjective:
    """Stated RPO/RTO objective for a run cohort."""

    max_rpo_seconds: float
    max_rto_seconds: float


@dataclass(frozen=True, slots=True)
class DrObjectiveReport:
    """Aggregate over a window of :class:`DrRunReport`s vs a stated objective.

    Emits median + p90 per phase-3 § RPO/RTO reporting. When the run
    count is zero, medians default to :data:`_MEDIAN_SENTINEL` — the
    caller renders that as "no data" rather than silently averaging.
    """

    objective: DrObjective
    run_count: int
    rpo_median_seconds: float
    rpo_p90_seconds: float
    rto_median_seconds: float
    rto_p90_seconds: float
    breach_count: int
    integrity_mismatches_total: int
    smoke_failures: int

    @property
    def rpo_objective_met(self) -> bool:
        if self.run_count == 0:
            return False
        return self.rpo_p90_seconds <= self.objective.max_rpo_seconds

    @property
    def rto_objective_met(self) -> bool:
        if self.run_count == 0:
            return False
        return self.rto_p90_seconds <= self.objective.max_rto_seconds


def summarize_runs(*, runs: Iterable[DrRunReport], objective: DrObjective) -> DrObjectiveReport:
    """Produce an :class:`DrObjectiveReport` from a run list.

    Empty run lists return sentinel medians so the caller can render
    "no data" rather than a false zero — phase-3 § RPO/RTO reporting.
    """
    runs_list = list(runs)
    if not runs_list:
        return DrObjectiveReport(
            objective=objective,
            run_count=0,
            rpo_median_seconds=_MEDIAN_SENTINEL,
            rpo_p90_seconds=_MEDIAN_SENTINEL,
            rto_median_seconds=_MEDIAN_SENTINEL,
            rto_p90_seconds=_MEDIAN_SENTINEL,
            breach_count=0,
            integrity_mismatches_total=0,
            smoke_failures=0,
        )

    rpos = sorted(r.rpo_seconds for r in runs_list)
    rtos = sorted(r.rto_seconds for r in runs_list)
    breach = sum(
        1
        for r in runs_list
        if r.rpo_seconds > objective.max_rpo_seconds or r.rto_seconds > objective.max_rto_seconds
    )

    return DrObjectiveReport(
        objective=objective,
        run_count=len(runs_list),
        rpo_median_seconds=median(rpos),
        rpo_p90_seconds=_percentile(rpos, 0.9),
        rto_median_seconds=median(rtos),
        rto_p90_seconds=_percentile(rtos, 0.9),
        breach_count=breach,
        integrity_mismatches_total=sum(r.integrity_mismatches for r in runs_list),
        smoke_failures=sum(1 for r in runs_list if not r.smoke_pass),
    )


def _percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile for a small sample.

    Matches the phase-3 doc's ``median and p90`` convention; robust to
    very small run counts (a fresh cohort).
    """
    if not sorted_values:
        return _MEDIAN_SENTINEL
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = max(1, int(round(p * len(sorted_values))))
    rank = min(rank, len(sorted_values))
    return sorted_values[rank - 1]


__all__ = [
    "DrExperiment",
    "DrObjective",
    "DrObjectiveReport",
    "DrRunReport",
    "DrScheduler",
    "DrSchedulerConfig",
    "FreezePeriod",
    "MaintenanceWindow",
    "SchedulerDecision",
    "SchedulerOutcome",
    "summarize_runs",
]
