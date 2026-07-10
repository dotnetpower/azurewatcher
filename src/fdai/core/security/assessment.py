"""Security Assessment report - fuse security findings into a graded report.

Design contract: ``docs/roadmap/assurance-twin.md`` (assessment output) and
the Azure SRE Agent parity note in
``docs/internals/sre-agent-gap-analysis.md`` (P3-9). Azure SRE Agent emits a
"Security Assessment" (for example an Application Gateway backend rated
CRITICAL, a detected vulnerability-scan attack). FDAI already assembles a
posture report from projection findings; this module is the security-scoped
counterpart: a deterministic fold over security-category
:class:`~fdai.shared.providers.projection.Finding` values into a graded,
grounded :class:`SecurityAssessment`.

Design invariants (identical to the posture report)
---------------------------------------------------

- **Read-only, pure**: a deterministic fold over a bounded
  ``Sequence[Finding]``; no I/O, no cloud SDK, no LLM. Same input yields
  identical output.
- **Grounded by construction**: every entry keeps the ``rule_id`` (cited
  evidence) and the source resource; the module never invents a finding
  or a recommendation.
- **Shadow-first**: ``blocks_action`` is ``True`` only when the pass ran in
  ``enforce`` mode AND the assessment is at or above the blocking
  threshold. A shadow pass records the truthful verdict but never gates an
  autonomous action.
- **CSP-neutral**: consumes only ``shared/providers/projection`` types.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.projection import Finding, Severity

_SEVERITY_ORDER: tuple[Severity, ...] = ("low", "medium", "high", "critical")
_SEVERITY_RANK: Mapping[Severity, int] = {s: i for i, s in enumerate(_SEVERITY_ORDER)}
# A finding at or above this severity is a blocker for the verdict.
_BLOCKING_SEVERITY: Severity = "high"


class SecurityVerdict(StrEnum):
    """Aggregate verdict for a security assessment."""

    CLEAR = "clear"
    """No finding at or above the blocking severity."""

    ATTENTION = "attention"
    """At least one ``high`` finding, no ``critical``."""

    CRITICAL = "critical"
    """At least one ``critical`` finding."""


@dataclass(frozen=True, slots=True)
class SecurityFindingEntry:
    """One security finding rendered for the report (grounded)."""

    rule_id: str
    resource_type: str
    resource_ref: str
    severity: Severity
    reason: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SecurityAssessment:
    """Graded security assessment over a bounded finding set."""

    scope: str
    assessed_at: datetime
    mode: Mode
    verdict: SecurityVerdict
    highest_severity: Severity | None
    counts_by_severity: Mapping[Severity, int]
    entries: tuple[SecurityFindingEntry, ...]
    blocks_action: bool = False
    summary: str = ""


def _verdict(highest: Severity | None) -> SecurityVerdict:
    if highest == "critical":
        return SecurityVerdict.CRITICAL
    if highest is not None and _SEVERITY_RANK[highest] >= _SEVERITY_RANK[_BLOCKING_SEVERITY]:
        return SecurityVerdict.ATTENTION
    return SecurityVerdict.CLEAR


def build_security_assessment(
    findings: Sequence[Finding],
    *,
    scope: str,
    assessed_at: datetime,
    mode: Mode = Mode.SHADOW,
) -> SecurityAssessment:
    """Fold security ``findings`` into a graded assessment (pure).

    Entries are sorted most-severe first, then by ``rule_id`` for a stable
    order. ``blocks_action`` is ``True`` only in enforce mode when the
    verdict is at or above the blocking severity - shadow never gates.
    """
    counts: dict[Severity, int] = dict.fromkeys(_SEVERITY_ORDER, 0)
    highest: Severity | None = None
    entries: list[SecurityFindingEntry] = []

    for finding in findings:
        counts[finding.severity] += 1
        if highest is None or _SEVERITY_RANK[finding.severity] > _SEVERITY_RANK[highest]:
            highest = finding.severity
        entries.append(
            SecurityFindingEntry(
                rule_id=finding.rule_id,
                resource_type=finding.resource.resource_type,
                resource_ref=finding.resource.ref,
                severity=finding.severity,
                reason=finding.reason,
                evidence_refs=finding.evidence_refs,
            )
        )

    entries.sort(key=lambda e: (-_SEVERITY_RANK[e.severity], e.rule_id))
    verdict = _verdict(highest)
    blocking = mode is Mode.ENFORCE and verdict is not SecurityVerdict.CLEAR
    summary = _summary(verdict=verdict, counts=counts, total=len(entries))

    return SecurityAssessment(
        scope=scope,
        assessed_at=assessed_at,
        mode=mode,
        verdict=verdict,
        highest_severity=highest,
        counts_by_severity=counts,
        entries=tuple(entries),
        blocks_action=blocking,
        summary=summary,
    )


def _summary(*, verdict: SecurityVerdict, counts: Mapping[Severity, int], total: int) -> str:
    if total == 0:
        return "No security findings in scope."
    parts = ", ".join(f"{counts[s]} {s}" for s in reversed(_SEVERITY_ORDER) if counts[s] > 0)
    return f"{verdict.value.upper()}: {total} finding(s) ({parts})."


__all__ = [
    "SecurityAssessment",
    "SecurityFindingEntry",
    "SecurityVerdict",
    "build_security_assessment",
]
