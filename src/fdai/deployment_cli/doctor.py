"""Read-only deployment toolchain diagnostics."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from fdai.deployment_cli.onboarding import OnboardingError, load_environment

DOCTOR_SCHEMA: Final = "fdai.deployment-cli.doctor.v1"
_COMMAND_TIMEOUT_SECONDS: Final = 20


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    """One non-sensitive diagnostic result."""

    check_id: str
    status: str
    summary: str
    remediation: str | None = None


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Stable machine-readable result for ``fdaictl doctor``."""

    checks: tuple[DoctorCheck, ...]
    schema: str = DOCTOR_SCHEMA

    @property
    def ready(self) -> bool:
        return all(check.status == "pass" for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "checks": [asdict(check) for check in self.checks],
            "ready": self.ready,
            "schema": self.schema,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


CommandRunner = Callable[[tuple[str, ...]], str]
ExecutableResolver = Callable[[str], str | None]


def run_doctor(
    *,
    config_path: Path | None = None,
    resolve_executable: ExecutableResolver = shutil.which,
    run_command: CommandRunner | None = None,
) -> DoctorReport:
    """Check required local tools and the active read-only Azure CLI context."""
    checks = [_python_check()]
    executables: dict[str, str] = {}
    for command in ("az", "terraform", "gh"):
        resolved = resolve_executable(command)
        if resolved is None:
            checks.append(
                DoctorCheck(
                    check_id=f"tool.{command}",
                    status="fail",
                    summary=f"{command} is not installed",
                    remediation=f"Install {command} and run fdaictl doctor again.",
                )
            )
        else:
            executables[command] = resolved
            checks.append(
                DoctorCheck(
                    check_id=f"tool.{command}",
                    status="pass",
                    summary=f"{command} is available",
                )
            )

    account: Mapping[str, Any] | None = None
    if "az" in executables:
        runner = run_command or _subprocess_runner
        auth_check, account = _azure_account_check(runner, executables["az"])
        checks.append(auth_check)
    else:
        checks.append(
            DoctorCheck(
                check_id="azure.auth",
                status="fail",
                summary="Azure authentication could not be checked",
                remediation="Install Azure CLI and run az login.",
            )
        )
    if config_path is not None:
        try:
            config = load_environment(config_path)
        except OnboardingError:
            checks.append(
                DoctorCheck(
                    check_id="deployment.config",
                    status="fail",
                    summary="Deployment configuration is invalid or unreadable",
                    remediation="Run fdaictl onboard init to create a valid configuration.",
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    check_id="deployment.config",
                    status="pass",
                    summary="Deployment configuration is valid",
                )
            )
            checks.append(
                _azure_target_check(
                    account,
                    config.azure.subscription_id,
                    config.azure.tenant_id,
                )
            )
    return DoctorReport(checks=tuple(checks))


def _python_check() -> DoctorCheck:
    supported = sys.version_info >= (3, 12)
    return DoctorCheck(
        check_id="runtime.python",
        status="pass" if supported else "fail",
        summary=f"Python {sys.version_info.major}.{sys.version_info.minor} is "
        f"{'supported' if supported else 'unsupported'}",
        remediation=None if supported else "Install Python 3.12 or newer.",
    )


def _azure_account_check(
    runner: CommandRunner, executable: str
) -> tuple[DoctorCheck, Mapping[str, Any] | None]:
    try:
        raw = runner((executable, "account", "show", "--output", "json"))
        account = json.loads(raw)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return (
            DoctorCheck(
                check_id="azure.auth",
                status="fail",
                summary="Azure CLI has no readable active account",
                remediation="Run az login and select the intended subscription.",
            ),
            None,
        )
    if not isinstance(account, Mapping):
        return (
            DoctorCheck(
                check_id="azure.auth",
                status="fail",
                summary="Azure CLI returned invalid account data",
                remediation="Run az account show and repair the Azure CLI profile.",
            ),
            None,
        )
    user = account.get("user")
    enabled_user = (
        account.get("state") == "Enabled"
        and isinstance(user, Mapping)
        and user.get("type") == "user"
    )
    if not enabled_user:
        return (
            DoctorCheck(
                check_id="azure.auth",
                status="fail",
                summary="Azure CLI requires an enabled interactive user account",
                remediation="Run az login with the intended operator identity.",
            ),
            None,
        )
    return (
        DoctorCheck(
            check_id="azure.auth",
            status="pass",
            summary="Azure CLI has an enabled interactive user account",
        ),
        account,
    )


def _azure_target_check(
    account: Mapping[str, Any] | None,
    expected_subscription: UUID,
    expected_tenant: UUID,
) -> DoctorCheck:
    if account is None:
        return DoctorCheck(
            check_id="azure.target",
            status="fail",
            summary="Azure deployment target could not be verified",
            remediation="Repair Azure CLI authentication and run doctor again.",
        )
    matches = account.get("id") == str(expected_subscription) and account.get("tenantId") == str(
        expected_tenant
    )
    if not matches:
        return DoctorCheck(
            check_id="azure.target",
            status="fail",
            summary="Active Azure account does not match the deployment configuration",
            remediation="Select the intended Azure account and run doctor again.",
        )
    return DoctorCheck(
        check_id="azure.target",
        status="pass",
        summary="Active Azure account matches the deployment configuration",
    )


def _subprocess_runner(args: tuple[str, ...]) -> str:
    completed = subprocess.run(  # noqa: S603 - executable is resolved by shutil.which
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=_COMMAND_TIMEOUT_SECONDS,
    )
    return completed.stdout


__all__ = ["DOCTOR_SCHEMA", "DoctorCheck", "DoctorReport", "run_doctor"]
