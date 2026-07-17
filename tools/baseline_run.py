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

- Metric 2 - auto-resolution rate
- Metric 4 - human touchpoints per 100 events

Guard metrics reported per scenario expectations (never computed here -
the runner records the *baseline* value so later phases have both a
success and guard reference).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
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
    expected_should_execute: bool
    observed_executed: bool
    observed_rolled_back: bool
    observed_policy_violation: bool

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


def _run(
    root: Path,
    observations_path: Path | None = None,
) -> tuple[list[ScenarioOutcome], dict[str, Any]]:
    agent = ReferenceAgent()
    scenarios = _load_scenarios(root)
    observations, reference_agent = _load_observations(observations_path, scenarios)
    outcomes: list[ScenarioOutcome] = []
    for raw in scenarios:
        expected = raw["expected"]
        observed = observations.get(str(raw["id"]))
        predicted_tier: str
        predicted_decision: str
        if observed is None:
            decision = agent.decide(raw["event"])
            predicted_tier = decision.tier
            predicted_decision = decision.decision
            executed = False
            rolled_back = False
            policy_violation = False
        else:
            predicted_tier = _observed_choice(observed, "predicted_tier", {"t0", "t1", "t2"})
            predicted_decision = _observed_choice(
                observed,
                "predicted_decision",
                {"auto", "hil", "abstain", "deny"},
            )
            executed = _observed_bool(observed, "executed")
            rolled_back = _observed_bool(observed, "rolled_back")
            policy_violation = _observed_bool(observed, "policy_violation")
        outcomes.append(
            ScenarioOutcome(
                scenario_id=raw["id"],
                domain=raw["domain"],
                expected_tier=expected["tier"],
                expected_decision=expected["decision"],
                predicted_tier=predicted_tier,
                predicted_decision=predicted_decision,
                expected_should_execute=bool(expected["guard"]["should_execute"]),
                observed_executed=executed,
                observed_rolled_back=rolled_back,
                observed_policy_violation=policy_violation,
            )
        )

    if not outcomes:
        raise SystemExit(f"no scenarios found under {root}")

    per_domain: dict[str, list[ScenarioOutcome]] = {}
    for oc in outcomes:
        per_domain.setdefault(oc.domain, []).append(oc)

    summary: dict[str, Any] = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "reference_agent": reference_agent,
        "scenario_set_version": next(iter(scenarios))["version"],
        "scenario_count": len(outcomes),
        "evidence": {
            "kind": "measured-observations"
            if observations_path is not None
            else "synthetic-harness",
            "claim_eligible": observations_path is not None and len(outcomes) >= 30,
            "minimum_claim_sample_size": 30,
        },
        "success_metrics": {
            "auto_resolution_rate": _rate(outcomes, lambda o: o.predicted_decision == "auto"),
            "hil_rate": _rate(outcomes, lambda o: o.predicted_decision == "hil"),
            "routed_correctly_rate": _rate(outcomes, lambda o: o.routed_correctly),
            "human_touchpoints_per_100_events": (
                sum(1 for o in outcomes if o.human_touchpoint) / len(outcomes) * 100
            ),
        },
        "confidence_intervals_95": {
            "auto_resolution_rate": _wilson_interval(
                sum(1 for outcome in outcomes if outcome.predicted_decision == "auto"),
                len(outcomes),
            ),
            "hil_rate": _wilson_interval(
                sum(1 for outcome in outcomes if outcome.predicted_decision == "hil"),
                len(outcomes),
            ),
            "routed_correctly_rate": _wilson_interval(
                sum(1 for outcome in outcomes if outcome.routed_correctly),
                len(outcomes),
            ),
        },
        "guard_metrics_baseline": _observed_guard_baseline(outcomes),
        "guard_metric_source": "observed reference outcomes",
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


def _observed_guard_baseline(outcomes: list[ScenarioOutcome]) -> dict[str, float]:
    if not outcomes:
        return {}
    executed = sum(1 for outcome in outcomes if outcome.observed_executed)
    false_positives = sum(
        1
        for outcome in outcomes
        if outcome.observed_executed and not outcome.expected_should_execute
    )
    false_negatives = sum(
        1
        for outcome in outcomes
        if not outcome.observed_executed and outcome.expected_should_execute
    )
    return {
        "execution_rate": executed / len(outcomes),
        "rollback_rate": (
            sum(1 for outcome in outcomes if outcome.observed_rolled_back) / executed
            if executed
            else 0.0
        ),
        "policy_violation_escape_rate": (
            sum(1 for outcome in outcomes if outcome.observed_policy_violation) / executed
            if executed
            else 0.0
        ),
        "false_positive_rate": false_positives / len(outcomes),
        "false_negative_rate": false_negatives / len(outcomes),
    }


def _wilson_interval(successes: int, total: int) -> dict[str, float | int]:
    if total < 1:
        return {"sample_size": 0, "lower": 0.0, "upper": 0.0}
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return {
        "sample_size": total,
        "lower": max(0.0, center - margin),
        "upper": min(1.0, center + margin),
    }


def _load_observations(
    path: Path | None,
    scenarios: list[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], str]:
    if path is None:
        return {}, ReferenceAgent.VERSION
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("outcomes"), list):
        raise ValueError("reference observations MUST contain an outcomes array")
    reference_agent = raw.get("reference_agent")
    if not isinstance(reference_agent, str) or not reference_agent:
        raise ValueError("reference observations MUST name reference_agent")
    expected_version = str(scenarios[0]["version"])
    if raw.get("scenario_set_version") != expected_version:
        raise ValueError("reference observations scenario_set_version mismatch")
    observations: dict[str, Mapping[str, Any]] = {}
    for item in raw["outcomes"]:
        if not isinstance(item, dict) or not isinstance(item.get("scenario_id"), str):
            raise ValueError("each reference outcome MUST contain scenario_id")
        scenario_id = item["scenario_id"]
        if scenario_id in observations:
            raise ValueError(f"duplicate reference outcome {scenario_id!r}")
        observations[scenario_id] = item
    expected_ids = {str(scenario["id"]) for scenario in scenarios}
    if set(observations) != expected_ids:
        raise ValueError("reference observations MUST cover the frozen scenario set exactly")
    return observations, reference_agent


def _observed_choice(raw: Mapping[str, Any], key: str, allowed: set[str]) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"reference outcome {key} MUST be one of {sorted(allowed)}")
    return value


def _observed_bool(raw: Mapping[str, Any], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"reference outcome {key} MUST be a boolean")
    return value


def _render_markdown(summary: Mapping[str, Any]) -> str:
    lines: list[str] = [
        f"# Baseline Report - {summary['scenario_set_version']}",
        "",
        "> Autogenerated by `tools/baseline_run.py`. Do not hand-edit - regenerate.",
        "",
        "## Environment",
        "",
        f"- **Reference agent**: `{summary['reference_agent']}`",
        f"- **Scenario count**: {summary['scenario_count']}",
        f"- **Generated at (UTC)**: {summary['generated_at']}",
        f"- **Evidence kind**: `{summary['evidence']['kind']}`",
        f"- **Claim eligible**: `{str(summary['evidence']['claim_eligible']).lower()}`",
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
        "## Statistical Confidence",
        "",
        "| Metric | Sample | 95% CI |",
        "|--------|-------:|--------|",
    ]
    for metric, interval in summary["confidence_intervals_95"].items():
        lines.append(
            f"| `{metric}` | {interval['sample_size']} | "
            f"{interval['lower']:.3f} - {interval['upper']:.3f} |"
        )

    lines += [
        "",
        "## Guard Baseline (observed reference outcomes)",
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
        f"# 베이스라인 리포트 - {summary['scenario_set_version']}",
        "",
        "> `tools/baseline_run.py` 로 자동 생성됩니다. 손대지 말고 재생성하세요.",
        "",
        "## 환경",
        "",
        f"- **참조 에이전트**: `{summary['reference_agent']}`",
        f"- **시나리오 수**: {summary['scenario_count']}",
        f"- **생성 시각 (UTC)**: {summary['generated_at']}",
        f"- **증거 종류**: `{summary['evidence']['kind']}`",
        f"- **자율성 주장 사용 가능**: `{str(summary['evidence']['claim_eligible']).lower()}`",
        "",
        "## 성공 지표",
        "",
        "| 지표 | 값 |",
        "|------|-----|",
    ]
    for metric, value in summary["success_metrics"].items():
        lines.append(f"| `{metric}` | {value:.3f} |")

    lines += [
        "",
        "## 통계 신뢰도",
        "",
        "| 지표 | 표본 | 95% 신뢰 구간 |",
        "|------|-----:|---------------|",
    ]
    for metric, interval in summary["confidence_intervals_95"].items():
        lines.append(
            f"| `{metric}` | {interval['sample_size']} | "
            f"{interval['lower']:.3f} - {interval['upper']:.3f} |"
        )

    lines += ["", "## 가드 베이스라인 (관측된 참조 결과)", "", "| 가드 | 비율 |", "|------|------|"]
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
    parser.add_argument(
        "--observations",
        type=Path,
        help="Measured reference outcomes JSON covering the frozen scenario set exactly.",
    )
    parser.add_argument("--json", type=Path, help="Write the JSON summary here.")
    parser.add_argument("--report", type=Path, help="Write the Markdown report here.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    _, summary = _run(args.scenarios, args.observations)

    stdout_summary = json.dumps(summary, indent=2)
    if args.json is None and args.report is None:
        print(stdout_summary)

    _write(args.json, stdout_summary + "\n")
    if args.report is not None:
        report_text = _render_markdown(summary)
        _write(args.report, report_text)
        # Emit the KO pair alongside so `docs/baselines/**` satisfies the
        # translation-pair gate. Reproduce `git hash-object`'s blob hashing
        # so the recorded SHA matches whatever a fresh `git hash-object`
        # call would return once the file is on disk.
        import hashlib

        report_bytes = report_text.encode("utf-8")
        source_sha = hashlib.sha1(  # noqa: S324 - matches git blob hashing, not a security primitive
            b"blob " + str(len(report_bytes)).encode() + b"\x00" + report_bytes,
            usedforsecurity=False,
        ).hexdigest()
        ko_path = args.report.with_name(args.report.stem + "-ko" + args.report.suffix)
        summary_with_source = dict(summary)
        summary_with_source["_source_filename"] = args.report.name
        _write(ko_path, _render_markdown_ko(summary_with_source, source_sha))

    return 0


if __name__ == "__main__":  # pragma: no cover - invoked as `python -m tools.baseline_run`
    raise SystemExit(main(sys.argv[1:]))
