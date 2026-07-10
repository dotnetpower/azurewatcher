"""Active plan reassembly - the bounded convergence loop.

When a :class:`~fdai.core.deploy_preflight.report.DeploymentReadinessReport`
is ``BLOCKED`` and every blocking finding carries an ``autofix``
``terraform_toggle`` resolution, this module drives a bounded loop that
accumulates the tfvars overrides that make the plan comply and re-checks the
reassembled plan through preflight again (verifier is authority). The loop
terminates on one of a small set of safety stop-conditions; anything it cannot
clear escalates to ``hil``.

Design: ``docs/roadmap/preflight-active-reassembly.md``.

Boundaries
----------
Pure ``core/`` decision logic. This module runs no terraform, opens no PR, and
imports no cloud SDK. The caller injects an async ``reanalyze`` callable that
takes the accumulated tfvars overrides, re-renders + re-plans the deployment,
and returns a fresh report. The rendered overrides are handed to the executor
(via the ``remediate.apply-preflight-toggle`` ActionType) which owns the PR and
the four safety invariants; this module only decides *what* to reassemble.

Fail-closed: a ``reanalyze`` (or probe) that raises propagates - the caller
degrades to ``hil`` rather than reassembling on a partial pass.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from fdai.core.deploy_preflight.report import (
    DeploymentReadinessReport,
    ReadinessVerdict,
)
from fdai.shared.providers.feasibility_probe import ProbeFinding, ResolutionKind

# Default cap on reassembly iterations. Configuration, not policy: a fork tunes
# it at the composition root. Kept small so a non-converging loop escalates to
# hil quickly rather than churning terraform plans.
_DEFAULT_MAX_ITERATIONS = 3

#: An async callable the caller injects: given the accumulated tfvars overrides,
#: re-render + re-plan the deployment and return a fresh readiness report.
ReanalyzeFn = Callable[[Mapping[str, str]], Awaitable[DeploymentReadinessReport]]


class ReassemblyStatus(StrEnum):
    """Terminal status of a reassembly loop."""

    CLEARED = "cleared"
    """The (reassembled) plan is no longer blocked; ``overrides`` make it comply."""

    ESCALATED = "escalated"
    """The loop could not clear the plan safely; route to ``hil``."""


class ReassemblyReason(StrEnum):
    """Why the loop reached its terminal status (audit-grade)."""

    NONE = "none"
    """Cleared with no escalation."""

    MANUAL_BLOCKER = "manual_blocker"
    """A blocking finding has no ``autofix`` toggle; partial fixes are never applied."""

    NON_CONVERGENT = "non_convergent"
    """The same toggle was proposed twice for one finding - it does not clear it."""

    REGRESSION = "regression"
    """A reassembly pass produced more blocking findings than the prior pass."""

    MAX_ITERATIONS = "max_iterations"
    """The iteration cap was reached with the plan still blocked."""


@dataclass(frozen=True, slots=True)
class ReassemblyOutcome:
    """The decision the loop reached - a side-effect-free value.

    ``overrides`` is the accumulated tfvars override map the executor would
    render into a remediation PR when ``status`` is ``CLEARED``. On escalation
    it holds whatever was accumulated before the loop gave up (useful context
    for the ``hil`` item) and MUST NOT be applied autonomously.
    """

    status: ReassemblyStatus
    reason: ReassemblyReason
    overrides: Mapping[str, str] = field(default_factory=dict)
    iterations: int = 0
    final_report: DeploymentReadinessReport | None = None


def _autofix_overrides(finding: ProbeFinding) -> dict[str, str] | None:
    """Return the tfvars overrides for an autofix toggle finding, else ``None``.

    Eligibility gate (see the design doc): the resolution MUST be a
    ``TERRAFORM_TOGGLE`` with ``autofix`` set and a non-empty ``set_vars``.
    A ``MANUAL`` resolution or a non-autofix toggle returns ``None`` so the
    loop routes the whole pass to ``hil``.
    """

    resolution = finding.resolution
    if (
        resolution.kind is ResolutionKind.TERRAFORM_TOGGLE
        and resolution.autofix
        and resolution.set_vars
    ):
        return dict(resolution.set_vars)
    return None


async def reassemble(
    *,
    initial_report: DeploymentReadinessReport,
    reanalyze: ReanalyzeFn,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
) -> ReassemblyOutcome:
    """Drive the bounded reassembly loop over ``initial_report``.

    Returns a :class:`ReassemblyOutcome`. Never mutates anything and never
    applies an override itself - it decides the reassembly and hands the
    accumulated overrides back to the caller. Propagates any exception raised
    by ``reanalyze`` (fail-closed: the caller degrades to ``hil``).
    """

    if max_iterations < 1:
        raise ValueError("max_iterations MUST be >= 1")

    report = initial_report
    overrides: dict[str, str] = {}
    # finding id -> the set of toggles already proposed for it, so a repeated
    # proposal (a toggle that did not clear its finding) is caught as non-convergence.
    proposed: dict[str, set[frozenset[tuple[str, str]]]] = {}
    iterations = 0

    while True:
        if report.verdict is not ReadinessVerdict.BLOCKED:
            return ReassemblyOutcome(
                status=ReassemblyStatus.CLEARED,
                reason=ReassemblyReason.NONE,
                overrides=dict(overrides),
                iterations=iterations,
                final_report=report,
            )

        # All-or-nothing: every blocking finding MUST have an autofix toggle.
        pass_toggles: dict[str, dict[str, str]] = {}
        for finding in report.blocking_findings:
            toggle = _autofix_overrides(finding)
            if toggle is None:
                return ReassemblyOutcome(
                    status=ReassemblyStatus.ESCALATED,
                    reason=ReassemblyReason.MANUAL_BLOCKER,
                    overrides=dict(overrides),
                    iterations=iterations,
                    final_report=report,
                )
            pass_toggles[finding.id] = toggle

        # Non-convergence: the same toggle proposed twice for one finding means
        # applying it did not clear that finding - stop before flip-flopping.
        for finding_id, toggle in pass_toggles.items():
            key = frozenset(toggle.items())
            if key in proposed.get(finding_id, set()):
                return ReassemblyOutcome(
                    status=ReassemblyStatus.ESCALATED,
                    reason=ReassemblyReason.NON_CONVERGENT,
                    overrides=dict(overrides),
                    iterations=iterations,
                    final_report=report,
                )
            proposed.setdefault(finding_id, set()).add(key)

        if iterations >= max_iterations:
            return ReassemblyOutcome(
                status=ReassemblyStatus.ESCALATED,
                reason=ReassemblyReason.MAX_ITERATIONS,
                overrides=dict(overrides),
                iterations=iterations,
                final_report=report,
            )

        prior_blocking = len(report.blocking_findings)
        for toggle in pass_toggles.values():
            overrides.update(toggle)
        iterations += 1

        report = await reanalyze(dict(overrides))

        if len(report.blocking_findings) > prior_blocking:
            return ReassemblyOutcome(
                status=ReassemblyStatus.ESCALATED,
                reason=ReassemblyReason.REGRESSION,
                overrides=dict(overrides),
                iterations=iterations,
                final_report=report,
            )


__all__ = [
    "ReanalyzeFn",
    "ReassemblyOutcome",
    "ReassemblyReason",
    "ReassemblyStatus",
    "reassemble",
]
