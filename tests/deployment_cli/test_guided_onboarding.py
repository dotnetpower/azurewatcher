"""Guided deployment onboarding order and fail-stop tests."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import fdai.deployment_cli.guided_onboarding as guided_module
from fdai.deployment_cli.cli import main
from fdai.deployment_cli.doctor import DoctorCheck, DoctorReport
from fdai.deployment_cli.guided_onboarding import (
    GuidedOnboardingError,
    GuidedOnboardingRequest,
    GuidedOnboardingResult,
    GuidedOnboardingStep,
    run_guided_onboarding,
)
from fdai.deployment_cli.onboarding import OnboardingResult
from fdai.deployment_cli.plan_submission import (
    PlanStatusResult,
    PlanSubmissionError,
    PlanSubmissionResult,
)
from fdai.deployment_cli.preflight import StaticPreflightResult


def _doctor(*, ready: bool = True) -> DoctorReport:
    return DoctorReport(
        checks=(
            DoctorCheck(
                check_id="guided.test",
                status="pass" if ready else "fail",
                summary="guided test",
            ),
        )
    )


def _request(tmp_path: Path) -> GuidedOnboardingRequest:
    return GuidedOnboardingRequest(
        environment="dev",
        region="koreacentral",
        config_path=tmp_path / "environment.json",
        preflight_input_path=tmp_path / "preflight.json",
        repository="example/fdai",
        bundle_digest="a" * 64,
        commit_sha="b" * 40,
    )


def _preflight(*, blocks: bool = False, findings: bool = False) -> StaticPreflightResult:
    report = SimpleNamespace(
        blocks_deploy=blocks,
        findings=(object(),) if findings else (),
    )
    return cast(StaticPreflightResult, SimpleNamespace(report=report))


def test_guided_module_exposes_no_apply_or_local_process_boundary() -> None:
    assert not hasattr(guided_module, "submit_github_apply")
    assert not hasattr(guided_module, "subprocess")


async def test_guided_onboarding_runs_guarded_plan_only_sequence(tmp_path: Path) -> None:
    calls: list[str] = []

    def doctor_runner(*, config_path: Path | None = None) -> DoctorReport:
        calls.append("doctor-toolchain" if config_path is None else "doctor-target")
        return _doctor()

    def initializer(**_: object) -> OnboardingResult:
        calls.append("config")
        return OnboardingResult(environment="dev", path=str(tmp_path / "environment.json"))

    async def preflight_runner(*_: object) -> StaticPreflightResult:
        calls.append("preflight")
        return _preflight(findings=True)

    async def submitter(**_: object) -> PlanSubmissionResult:
        calls.append("runner-submission")
        return PlanSubmissionResult(
            submission_id="123",
            plan_id="plan-123-1",
            workflow_url="https://github.com/example/fdai/actions/runs/123",
        )

    async def status_reader(**_: object) -> PlanStatusResult:
        calls.append("post-check")
        return PlanStatusResult(
            plan_id="plan-123-1",
            plan_digest="c" * 64,
            created_at="2026-07-17T00:00:00Z",
            expires_at="2026-07-17T01:00:00Z",
            status="planning",
            workflow_url="https://github.com/example/fdai/actions/runs/123",
        )

    result = await run_guided_onboarding(
        _request(tmp_path),
        doctor_runner=doctor_runner,
        environment_initializer=initializer,
        preflight_runner=preflight_runner,
        plan_submitter=submitter,
        status_reader=status_reader,
    )

    assert calls == [
        "doctor-toolchain",
        "config",
        "doctor-target",
        "preflight",
        "runner-submission",
        "post-check",
    ]
    assert [step.step_id for step in result.steps] == calls
    assert result.steps[3].status == "warning"
    assert result.plan_status == "planning"
    assert "subscription" not in result.to_json()


async def test_guided_onboarding_stops_before_config_when_doctor_fails(
    tmp_path: Path,
) -> None:
    initialized = False

    def initializer(**_: object) -> OnboardingResult:  # pragma: no cover - must not run
        nonlocal initialized
        initialized = True
        raise AssertionError("config must not run")

    with pytest.raises(GuidedOnboardingError, match="doctor checks failed") as error:
        await run_guided_onboarding(
            _request(tmp_path),
            doctor_runner=lambda **_: _doctor(ready=False),
            environment_initializer=initializer,
        )

    assert error.value.step_id == "doctor-toolchain"
    assert initialized is False


async def test_guided_onboarding_stops_before_submission_on_preflight_block(
    tmp_path: Path,
) -> None:
    submitted = False

    async def submitter(**_: object) -> PlanSubmissionResult:  # pragma: no cover - must not run
        nonlocal submitted
        submitted = True
        raise AssertionError("submission must not run")

    with pytest.raises(GuidedOnboardingError, match="reported a blocker") as error:
        await run_guided_onboarding(
            _request(tmp_path),
            doctor_runner=lambda **_: _doctor(),
            environment_initializer=lambda **_: OnboardingResult(
                environment="dev", path=str(tmp_path / "environment.json")
            ),
            preflight_runner=lambda *_: _async_preflight(blocks=True),
            plan_submitter=submitter,
        )

    assert error.value.step_id == "preflight"
    assert submitted is False


async def test_guided_onboarding_rejects_failed_post_check(tmp_path: Path) -> None:
    async def status_reader(**_: object) -> PlanStatusResult:
        return PlanStatusResult(
            plan_id="plan-123-1",
            plan_digest="c" * 64,
            created_at="2026-07-17T00:00:00Z",
            expires_at="2026-07-17T01:00:00Z",
            status="failed",
            workflow_url="https://github.com/example/fdai/actions/runs/123",
        )

    with pytest.raises(GuidedOnboardingError, match="unsafe state") as error:
        await run_guided_onboarding(
            _request(tmp_path),
            doctor_runner=lambda **_: _doctor(),
            environment_initializer=lambda **_: OnboardingResult(
                environment="dev", path=str(tmp_path / "environment.json")
            ),
            preflight_runner=lambda *_: _async_preflight(),
            plan_submitter=lambda **_: _async_submission(),
            status_reader=status_reader,
        )

    assert error.value.step_id == "post-check"


async def test_guided_onboarding_retries_only_missing_plan_metadata(tmp_path: Path) -> None:
    attempts = 0
    delays: list[float] = []

    async def status_reader(**_: object) -> PlanStatusResult:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PlanSubmissionError("GitHub plan metadata artifact is missing or ambiguous")
        return PlanStatusResult(
            plan_id="plan-123-1",
            plan_digest="c" * 64,
            created_at="2026-07-17T00:00:00Z",
            expires_at="2026-07-17T01:00:00Z",
            status="ready",
            workflow_url="https://github.com/example/fdai/actions/runs/123",
        )

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    result = await run_guided_onboarding(
        _request(tmp_path),
        doctor_runner=lambda **_: _doctor(),
        environment_initializer=lambda **_: OnboardingResult(
            environment="dev", path=str(tmp_path / "environment.json")
        ),
        preflight_runner=lambda *_: _async_preflight(),
        plan_submitter=lambda **_: _async_submission(),
        status_reader=status_reader,
        post_check_attempts=2,
        post_check_interval_seconds=0.25,
        sleeper=sleeper,
    )

    assert result.plan_status == "ready"
    assert attempts == 2
    assert delays == [0.25]


def test_cli_guided_onboarding_emits_stable_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[GuidedOnboardingRequest] = []

    async def guided(request: GuidedOnboardingRequest) -> GuidedOnboardingResult:
        captured.append(request)
        return GuidedOnboardingResult(
            steps=(
                GuidedOnboardingStep(
                    step_id="post-check",
                    status="pass",
                    summary="Sanitized plan status is available",
                ),
            ),
            config_path=str(request.config_path),
            submission_id="123",
            plan_id="plan-123-1",
            plan_status="planning",
            workflow_url="https://github.com/example/fdai/actions/runs/123",
        )

    monkeypatch.setattr("fdai.deployment_cli.cli.run_guided_onboarding", guided)
    output = io.StringIO()
    config_path = tmp_path / "environment.json"

    exit_code = main(
        [
            "onboard",
            "guided",
            "--environment",
            "dev",
            "--region",
            "koreacentral",
            "--config",
            str(config_path),
            "--preflight-input",
            str(tmp_path / "preflight.json"),
            "--repository",
            "example/fdai",
            "--bundle-digest",
            "a" * 64,
            "--commit-sha",
            "b" * 40,
            "--output",
            "json",
        ],
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    assert exit_code == 0
    assert captured[0].config_path == config_path
    assert payload["schema_version"] == "fdai.deployment-cli.guided-onboarding.v1"
    assert payload["plan_status"] == "planning"


def test_cli_guided_failure_reports_only_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def guided(_: GuidedOnboardingRequest) -> GuidedOnboardingResult:
        raise GuidedOnboardingError("preflight", "Deployment preflight reported a blocker")

    monkeypatch.setattr("fdai.deployment_cli.cli.run_guided_onboarding", guided)
    output = io.StringIO()

    exit_code = main(
        [
            "onboard",
            "guided",
            "--environment",
            "dev",
            "--region",
            "koreacentral",
            "--config",
            "environment.json",
            "--preflight-input",
            "preflight.json",
            "--repository",
            "example/fdai",
            "--bundle-digest",
            "a" * 64,
            "--commit-sha",
            "b" * 40,
            "--output",
            "json",
        ],
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    assert exit_code == 4
    assert payload["failed_step"] == "preflight"
    assert set(payload) == {"error", "failed_step", "schema_version"}


async def _async_preflight(*, blocks: bool = False) -> StaticPreflightResult:
    return _preflight(blocks=blocks)


async def _async_submission() -> PlanSubmissionResult:
    return PlanSubmissionResult(
        submission_id="123",
        plan_id="plan-123-1",
        workflow_url="https://github.com/example/fdai/actions/runs/123",
    )
