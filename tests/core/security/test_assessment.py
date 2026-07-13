"""Tests for the security assessment report generator."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.security.assessment import (
    SecurityVerdict,
    build_security_assessment,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.projection import Finding, ResourceRef

_AT = datetime(2026, 7, 10, tzinfo=UTC)


def _finding(rule_id: str, severity: str, ref: str = "appgw-1") -> Finding:
    return Finding(
        rule_id=rule_id,
        resource=ResourceRef(resource_type="application-gateway", ref=ref),
        severity=severity,  # type: ignore[arg-type]
        reason=f"{rule_id} tripped",
        evidence_refs=(f"log/{rule_id}",),
    )


def test_off_list_severity_fails_toward_safety_not_crash() -> None:
    # Severity is a Literal, not a runtime enum; a fork / deserialized finding
    # can carry an unexpected value. The fold must not crash - it ranks an
    # unknown severity as most-severe (blocking), mirroring the readiness guard.
    report = build_security_assessment(
        [_finding("weird", "catastrophic")], scope="s", assessed_at=_AT, mode=Mode.ENFORCE
    )
    assert report.verdict is SecurityVerdict.ATTENTION  # unknown -> blocking, not CLEAR
    assert report.blocks_action is True
    assert report.highest_severity == "catastrophic"


def test_empty_findings_is_clear() -> None:
    report = build_security_assessment([], scope="sub-1", assessed_at=_AT)
    assert report.verdict is SecurityVerdict.CLEAR
    assert report.highest_severity is None
    assert report.blocks_action is False
    assert report.summary == "No security findings in scope."


def test_critical_finding_yields_critical_verdict() -> None:
    report = build_security_assessment(
        [_finding("waf-502", "critical"), _finding("tls-weak", "medium")],
        scope="sub-1",
        assessed_at=_AT,
    )
    assert report.verdict is SecurityVerdict.CRITICAL
    assert report.highest_severity == "critical"
    # Most-severe entry sorts first.
    assert report.entries[0].rule_id == "waf-502"
    assert report.counts_by_severity["critical"] == 1
    assert "CRITICAL" in report.summary


def test_high_without_critical_is_attention() -> None:
    report = build_security_assessment([_finding("r", "high")], scope="s", assessed_at=_AT)
    assert report.verdict is SecurityVerdict.ATTENTION


def test_low_and_medium_only_is_clear() -> None:
    report = build_security_assessment(
        [_finding("a", "low"), _finding("b", "medium")], scope="s", assessed_at=_AT
    )
    assert report.verdict is SecurityVerdict.CLEAR


def test_shadow_never_blocks_but_enforce_does() -> None:
    findings = [_finding("waf-502", "critical")]
    shadow = build_security_assessment(findings, scope="s", assessed_at=_AT, mode=Mode.SHADOW)
    enforce = build_security_assessment(findings, scope="s", assessed_at=_AT, mode=Mode.ENFORCE)
    assert shadow.blocks_action is False
    assert enforce.blocks_action is True


def test_enforce_clear_does_not_block() -> None:
    report = build_security_assessment(
        [_finding("a", "low")], scope="s", assessed_at=_AT, mode=Mode.ENFORCE
    )
    assert report.verdict is SecurityVerdict.CLEAR
    assert report.blocks_action is False


def test_entries_preserve_grounding() -> None:
    report = build_security_assessment([_finding("waf-502", "high")], scope="s", assessed_at=_AT)
    entry = report.entries[0]
    assert entry.rule_id == "waf-502"
    assert entry.resource_type == "application-gateway"
    assert entry.evidence_refs == ("log/waf-502",)


def test_stable_sort_by_severity_then_rule_id() -> None:
    report = build_security_assessment(
        [_finding("z", "high"), _finding("a", "high"), _finding("m", "critical")],
        scope="s",
        assessed_at=_AT,
    )
    assert [e.rule_id for e in report.entries] == ["m", "a", "z"]
