"""Baseline runner + reference-agent smoke tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.baseline_run import _run
from tools.reference_agent import AgentDecision, ReferenceAgent

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = REPO_ROOT / "tests" / "scenarios" / "v2026.07"


def test_reference_agent_is_deterministic() -> None:
    """Two invocations of the reference agent yield byte-identical outputs."""
    agent_a = ReferenceAgent()
    agent_b = ReferenceAgent()
    event = {
        "schema_version": "1.0.0",
        "event_id": "00000000-0000-0000-0000-000000000001",
        "source": "example_source",
        "event_type": "change_detected",
    }
    a = agent_a.decide(event)
    b = agent_b.decide(event)
    assert a == b
    assert isinstance(a, AgentDecision)
    assert a.decision == "hil"


def test_run_produces_the_expected_summary_shape() -> None:
    _, summary = _run(SCENARIOS)
    assert summary["scenario_count"] == 9
    assert summary["reference_agent"] == ReferenceAgent.VERSION
    assert "success_metrics" in summary
    assert "guard_metrics_baseline" in summary
    assert "per_domain" in summary
    assert set(summary["per_domain"]) == {"change", "dr", "finops"}
    # Stub always routes to HIL → auto rate is 0.
    assert summary["success_metrics"]["auto_resolution_rate"] == 0.0
    assert summary["success_metrics"]["hil_rate"] == 1.0


def test_run_is_reproducible() -> None:
    """Same scenario version + same agent version → same summary."""
    _, first = _run(SCENARIOS)
    _, second = _run(SCENARIOS)
    # `generated_at` timestamps differ between runs; every other key MUST match.
    first_copy = dict(first)
    second_copy = dict(second)
    del first_copy["generated_at"]
    del second_copy["generated_at"]
    assert first_copy == second_copy


def test_cli_writes_report_and_json(tmp_path: Path) -> None:
    """`python -m tools.baseline_run` runs green and produces both artifacts."""
    report = tmp_path / "report.md"
    payload = tmp_path / "summary.json"

    result = subprocess.run(  # noqa: S603 — controlled subprocess
        [
            sys.executable,
            "-m",
            "tools.baseline_run",
            "--scenarios",
            str(SCENARIOS),
            "--json",
            str(payload),
            "--report",
            str(report),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert report.exists()
    assert payload.exists()

    parsed = json.loads(payload.read_text(encoding="utf-8"))
    assert parsed["scenario_count"] == 9

    # The KO sibling MUST have been emitted alongside the EN report.
    ko_sibling = report.with_name(report.stem + "-ko" + report.suffix)
    assert ko_sibling.exists()
