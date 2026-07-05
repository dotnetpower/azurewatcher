"""Phase 0 baseline runner.

Replays a frozen scenario set through the :class:`ReferenceAgent` and
emits both a machine-readable JSON summary and a Markdown report.

Usage
-----

.. code-block:: shell

    python -m tools.baseline_run --scenarios tests/scenarios/v2026.07
    python -m tools.baseline_run \
        --scenarios tests/scenarios/v2026.07 \
        --json docs/baselines/v2026.07.json \
        --report docs/baselines/v2026.07.md

Success metrics reported (from `goals-and-metrics.md`):

- Metric 2 — auto-resolution rate
- Metric 4 — human touchpoints per 100 events

Guard metrics reported per scenario expectations (never computed here —
the runner records the *baseline* value so later phases have both a
success and guard reference).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from tools.reference_agent import ReferenceAgent


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    scenario_id: str
    domain: str
    expected_tier: str
    expected_decision: str
    predicted_tier: str
    predicted_decision: str

    @property
    def routed_correctly(self) -> bool:
        return (
            self.expected_tier == self.predicted_tier
            and self.expected_decision == self.predicted_decision
        )

    @property
    def human_touchpoint(self) -> bool:
        return self.predicted_decision == "hil"


def _load_scenarios(root: Path) -> list[Mapping[str, Any]]:
    scenarios: list[Mapping[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        scenarios.append(json.loads(path.read_text(encoding="utf-8")))
    return scenarios


def _run(root: Path) -> tuple[list[ScenarioOutcome], dict[str, Any]]:
    agent = ReferenceAgent()
    outcomes: list[ScenarioOutcome] = []
    for raw in _load_scenarios(root):
        expected = raw["expected"]
        decision = agent.decide(raw["event"])
        outcomes.append(
            ScenarioOutcome(
                scenario_id=raw["id"],
                domain=raw["domain"],
                expected_tier=expected["tier"],
                expected_decision=expected["decision"],
                predicted_tier=decision.tier,
                predicted_decision=decision.decision,
            )
        )

    if not outcomes:
        raise SystemExit(f"no scenarios found under {root}")

    per_domain: dict[str, list[ScenarioOutcome]] = {}
    for oc in outcomes:
        per_domain.setdefault(oc.domain, []).append(oc)

    summary: dict[str, Any] = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "reference_agent": ReferenceAgent.VERSION,
        "scenario_set_version": next(iter(_load_scenarios(root)))["version"],
        "scenario_count": len(outcomes),
        "success_metrics": {
            "auto_resolution_rate": _rate(outcomes, lambda o: o.predicted_decision == "auto"),
            "hil_rate": _rate(outcomes, lambda o: o.predicted_decision == "hil"),
            "routed_correctly_rate": _rate(outcomes, lambda o: o.routed_correctly),
            "human_touchpoints_per_100_events": (
                sum(1 for o in outcomes if o.human_touchpoint) / len(outcomes) * 100
            ),
        },
        "guard_metrics_baseline": _guard_baseline(root),
        "per_domain": {
            domain: {
                "count": len(items),
                "auto_resolution_rate": _rate(items, lambda o: o.predicted_decision == "auto"),
                "hil_rate": _rate(items, lambda o: o.predicted_decision == "hil"),
                "routed_correctly_rate": _rate(items, lambda o: o.routed_correctly),
            }
            for domain, items in sorted(per_domain.items())
        },
    }
    return outcomes, summary


def _rate(items: list[ScenarioOutcome], predicate: Any) -> float:
    return sum(1 for o in items if predicate(o)) / len(items) if items else 0.0


def _guard_baseline(root: Path) -> dict[str, float]:
    """Aggregate guard expectations across the scenario set.

    Even though the reference agent never executes, we still record the
    guard *baseline* the scenario set claims so downstream phases have a
    numeric reference.
    """
    raws = _load_scenarios(root)
    if not raws:
        return {}
    execs = [1 if r["expected"]["guard"]["should_execute"] else 0 for r in raws]
    rollb = [1 if r["expected"]["guard"]["should_rollback"] else 0 for r in raws]
    viols = [1 if r["expected"]["guard"]["should_trigger_policy_violation"] else 0 for r in raws]
    return {
        "expected_execute_rate": mean(execs),
        "expected_rollback_rate": mean(rollb),
        "expected_policy_violation_rate": mean(viols),
    }


def _render_markdown(summary: Mapping[str, Any]) -> str:
    lines: list[str] = [
        f"# Baseline Report — {summary['scenario_set_version']}",
        "",
        "> Autogenerated by `tools/baseline_run.py`. Do not hand-edit — regenerate.",
        "",
        "## Environment",
        "",
        f"- **Reference agent**: `{summary['reference_agent']}`",
        f"- **Scenario count**: {summary['scenario_count']}",
        f"- **Generated at (UTC)**: {summary['generated_at']}",
        "",
        "## Success Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
    ]
    for metric, value in summary["success_metrics"].items():
        lines.append(f"| `{metric}` | {value:.3f} |")

    lines += [
        "",
        "## Guard Baseline (from scenario expectations)",
        "",
        "| Guard | Rate |",
        "|-------|------|",
    ]
    for metric, value in summary["guard_metrics_baseline"].items():
        lines.append(f"| `{metric}` | {value:.3f} |")

    lines += [
        "",
        "## Per-Domain Breakdown",
        "",
        "| Domain | Count | Auto | HIL | Correctly Routed |",
        "|--------|-------|------|-----|------------------|",
    ]
    for domain, stats in summary["per_domain"].items():
        lines.append(
            f"| {domain} | {stats['count']} | "
            f"{stats['auto_resolution_rate']:.3f} | "
            f"{stats['hil_rate']:.3f} | "
            f"{stats['routed_correctly_rate']:.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_markdown_ko(summary: Mapping[str, Any], source_sha: str) -> str:
    """Korean sibling for the report. Headers translated; table values keep EN keys."""
    lines: list[str] = [
        "---",
        f"translation_of: {Path(summary['_source_filename']).name}",
        f"translation_source_sha: {source_sha}",
        f"translation_revised: {datetime.now(tz=UTC).date().isoformat()}",
        "---",
        "",
        f"# 베이스라인 리포트 — {summary['scenario_set_version']}",
        "",
        "> `tools/baseline_run.py` 로 자동 생성됩니다. 손대지 말고 재생성하세요.",
        "",
        "## 환경",
        "",
        f"- **참조 에이전트**: `{summary['reference_agent']}`",
        f"- **시나리오 수**: {summary['scenario_count']}",
        f"- **생성 시각 (UTC)**: {summary['generated_at']}",
        "",
        "## 성공 지표",
        "",
        "| 지표 | 값 |",
        "|------|-----|",
    ]
    for metric, value in summary["success_metrics"].items():
        lines.append(f"| `{metric}` | {value:.3f} |")

    lines += ["", "## 가드 베이스라인 (시나리오 예상값)", "", "| 가드 | 비율 |", "|------|------|"]
    for metric, value in summary["guard_metrics_baseline"].items():
        lines.append(f"| `{metric}` | {value:.3f} |")

    lines += [
        "",
        "## 도메인별 분해",
        "",
        "| 도메인 | 개수 | Auto | HIL | 올바르게 라우팅 |",
        "|--------|------|------|-----|------------------|",
    ]
    for domain, stats in summary["per_domain"].items():
        lines.append(
            f"| {domain} | {stats['count']} | "
            f"{stats['auto_resolution_rate']:.3f} | "
            f"{stats['hil_rate']:.3f} | "
            f"{stats['routed_correctly_rate']:.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _write(path: Path | None, content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="baseline-run", description=__doc__)
    parser.add_argument(
        "--scenarios",
        required=True,
        type=Path,
        help="Frozen scenario-set directory (e.g. tests/scenarios/v2026.07).",
    )
    parser.add_argument("--json", type=Path, help="Write the JSON summary here.")
    parser.add_argument("--report", type=Path, help="Write the Markdown report here.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    _, summary = _run(args.scenarios)

    stdout_summary = json.dumps(summary, indent=2)
    if args.json is None and args.report is None:
        print(stdout_summary)

    _write(args.json, stdout_summary + "\n")
    if args.report is not None:
        report_text = _render_markdown(summary) + "\n"
        _write(args.report, report_text)
        # Emit the KO pair alongside so `docs/baselines/**` satisfies the
        # translation-pair gate. Reproduce `git hash-object`'s blob hashing
        # so the recorded SHA matches whatever a fresh `git hash-object`
        # call would return once the file is on disk.
        import hashlib

        report_bytes = report_text.encode("utf-8")
        source_sha = hashlib.sha1(  # noqa: S324 — matches git blob hashing, not a security primitive
            b"blob " + str(len(report_bytes)).encode() + b"\x00" + report_bytes,
            usedforsecurity=False,
        ).hexdigest()
        ko_path = args.report.with_name(args.report.stem + "-ko" + args.report.suffix)
        summary_with_source = dict(summary)
        summary_with_source["_source_filename"] = args.report.name
        _write(ko_path, _render_markdown_ko(summary_with_source, source_sha) + "\n")

    return 0


if __name__ == "__main__":  # pragma: no cover — invoked as `python -m tools.baseline_run`
    raise SystemExit(main(sys.argv[1:]))
