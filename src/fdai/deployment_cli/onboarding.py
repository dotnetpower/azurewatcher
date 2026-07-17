"""Create schema-validated local deployment configuration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONFIG_SCHEMA: Final = "fdai.deployment.environment.v1"
ONBOARD_RESULT_SCHEMA: Final = "fdai.deployment-cli.onboard.v1"
_COMMAND_TIMEOUT_SECONDS: Final = 20
EnvironmentName = Literal["dev", "staging", "prod"]


class _ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AzureTarget(_ConfigModel):
    """Non-secret Azure deployment target identity."""

    subscription_id: UUID
    tenant_id: UUID
    region: Annotated[str, Field(pattern=r"^[a-z0-9]{2,32}$")]


class DeploymentEnvironment(_ConfigModel):
    """Local source of truth used before a remote deployment is submitted."""

    schema_version: Literal["fdai.deployment.environment.v1"] = CONFIG_SCHEMA
    environment: EnvironmentName
    azure: AzureTarget
    execution_target: Literal["remote-runner"] = "remote-runner"
    autonomy_mode_default: Literal["shadow"] = "shadow"


class OnboardingResult(_ConfigModel):
    schema_version: Literal["fdai.deployment-cli.onboard.v1"] = ONBOARD_RESULT_SCHEMA
    environment: str
    path: str

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))


class OnboardingError(RuntimeError):
    """The local environment configuration could not be created safely."""

    def to_json(self) -> str:
        return json.dumps(
            {"error": str(self), "schema_version": ONBOARD_RESULT_SCHEMA},
            sort_keys=True,
            separators=(",", ":"),
        )


CommandRunner = Callable[[tuple[str, ...]], str]


def initialize_environment(
    *,
    environment: EnvironmentName,
    region: str,
    destination: Path | None = None,
    force: bool = False,
    run_command: CommandRunner | None = None,
    resolve_executable: Callable[[str], str | None] = shutil.which,
) -> OnboardingResult:
    """Capture the active Azure target into an untracked, mode-0600 JSON file."""
    path = destination or Path(".fdai") / "environments" / f"{environment}.json"
    executable = resolve_executable("az")
    if executable is None:
        raise OnboardingError("Azure CLI is not installed; install it and run az login")
    runner = run_command or _subprocess_runner
    try:
        account = _parse_account(runner((executable, "account", "show", "--output", "json")))
        config = DeploymentEnvironment(
            environment=environment,
            azure=AzureTarget(
                subscription_id=account["id"],
                tenant_id=account["tenantId"],
                region=region,
            ),
        )
    except (
        KeyError,
        OSError,
        subprocess.SubprocessError,
        ValidationError,
        json.JSONDecodeError,
    ) as exc:
        raise OnboardingError(
            "Azure CLI account or environment settings are invalid; run fdaictl doctor"
        ) from exc

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        message = f"configuration already exists at {path}; use --force to replace it"
        raise OnboardingError(message) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(config.model_dump_json(indent=2))
            stream.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return OnboardingResult(environment=environment, path=str(path))


def load_environment(path: Path) -> DeploymentEnvironment:
    """Load and validate a local deployment environment."""
    try:
        return DeploymentEnvironment.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise OnboardingError(f"configuration at {path} is invalid or unreadable") from exc


def _parse_account(raw: str) -> Mapping[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise OnboardingError("Azure CLI returned invalid account data")
    user = value.get("user")
    if (
        value.get("state") != "Enabled"
        or not isinstance(user, Mapping)
        or user.get("type") != "user"
    ):
        raise OnboardingError("Azure CLI requires an enabled interactive user account")
    return value


def _subprocess_runner(args: tuple[str, ...]) -> str:
    completed = subprocess.run(  # noqa: S603 - executable is resolved by shutil.which
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=_COMMAND_TIMEOUT_SECONDS,
    )
    return completed.stdout


__all__ = [
    "CONFIG_SCHEMA",
    "DeploymentEnvironment",
    "OnboardingError",
    "OnboardingResult",
    "initialize_environment",
    "load_environment",
]
