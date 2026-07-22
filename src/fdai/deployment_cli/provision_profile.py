"""Private local profile for a selected provisioning execution path."""

from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
from typing import Annotated, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fdai.deployment_cli.provision_inspect import (
    Connectivity,
    ExecutionHost,
    ExecutionTransport,
)

PROVISION_PROFILE_SCHEMA: Final = "fdai.deployment.provision-profile.v1"
PROVISION_PROFILE_RESULT_SCHEMA: Final = "fdai.deployment-cli.provision-profile.v1"
DEFAULT_PROFILE_PATH: Final = Path(".fdai/provisioning/profile.json")
AccessMethod = Literal[
    "internal_ssh",
    "temporary_public_ssh",
    "github_actions",
    "azure_bastion",
    "azure_run_command_emergency",
]


class _ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class TemporaryPublicSsh(_ProfileModel):
    """Bounded public SSH request; Azure Policy is checked before planning."""

    source_cidr: str
    access_window_minutes: Annotated[int, Field(ge=5, le=60)] = 30

    @model_validator(mode="after")
    def validate_source_cidr(self) -> TemporaryPublicSsh:
        try:
            network = ipaddress.ip_network(self.source_cidr, strict=True)
        except ValueError as exc:
            raise ValueError("source_cidr MUST be a canonical IP network") from exc
        if network.prefixlen == 0:
            raise ValueError("source_cidr MUST NOT allow the entire address space")
        return self


class ProvisioningProfile(_ProfileModel):
    """One explicit, non-secret provisioning profile selected after inspection."""

    schema_version: Literal["fdai.deployment.provision-profile.v1"] = PROVISION_PROFILE_SCHEMA
    connectivity: Connectivity
    execution_host: ExecutionHost
    transport: ExecutionTransport
    access_method: AccessMethod
    artifact_source: str | None = None
    temporary_public_ssh: TemporaryPublicSsh | None = None
    ownership: Literal["fdai-managed"] = "fdai-managed"
    required_human_approvers: Literal[1] = 1
    require_distinct_executor_identity: Literal[True] = True
    managed_vm_lifecycle: Literal["persistent_deallocated"] = "persistent_deallocated"

    @model_validator(mode="after")
    def validate_profile(self) -> ProvisioningProfile:
        if self.connectivity is Connectivity.AUTO:
            raise ValueError("connectivity MUST be explicitly online or offline")
        if self.execution_host is ExecutionHost.AUTO:
            raise ValueError("execution_host MUST be explicitly selected")
        if self.transport is ExecutionTransport.AUTO:
            raise ValueError("transport MUST be explicitly selected")
        if self.connectivity is Connectivity.OFFLINE and not self.artifact_source:
            raise ValueError("offline connectivity requires artifact_source")
        if self.connectivity is Connectivity.ONLINE and self.artifact_source is not None:
            raise ValueError("online connectivity MUST NOT set artifact_source")
        if self.transport is ExecutionTransport.GITHUB_ACTIONS:
            if self.access_method != "github_actions":
                raise ValueError("github-actions transport requires github_actions access")
        elif self.access_method == "github_actions":
            raise ValueError("github_actions access requires github-actions transport")
        if self.access_method == "temporary_public_ssh":
            if self.temporary_public_ssh is None:
                raise ValueError("temporary public SSH requires bounded access settings")
        elif self.temporary_public_ssh is not None:
            raise ValueError("temporary public SSH settings require that access method")
        return self


class ProvisionProfileError(RuntimeError):
    """A provisioning profile could not be created or loaded safely."""


class ProvisionProfileResult(_ProfileModel):
    schema_version: Literal["fdai.deployment-cli.provision-profile.v1"] = (
        PROVISION_PROFILE_RESULT_SCHEMA
    )
    path: str
    connectivity: str
    execution_host: str
    transport: str
    access_method: str
    mutation_performed: Literal[False] = False

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))


def initialize_provision_profile(
    *,
    connectivity: Connectivity,
    execution_host: ExecutionHost,
    transport: ExecutionTransport,
    access_method: str,
    artifact_source: str | None = None,
    source_cidr: str | None = None,
    access_window_minutes: int = 30,
    destination: Path = DEFAULT_PROFILE_PATH,
    force: bool = False,
) -> ProvisionProfileResult:
    """Validate and atomically write one mode-0600 provisioning profile."""
    try:
        profile = ProvisioningProfile(
            connectivity=connectivity,
            execution_host=execution_host,
            transport=transport,
            access_method=cast(AccessMethod, access_method),
            artifact_source=artifact_source,
            temporary_public_ssh=(
                TemporaryPublicSsh(
                    source_cidr=source_cidr or "",
                    access_window_minutes=access_window_minutes,
                )
                if access_method == "temporary_public_ssh"
                else None
            ),
        )
    except ValidationError as exc:
        raise ProvisionProfileError("provisioning profile settings are invalid") from exc

    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.parent.chmod(0o700)
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise ProvisionProfileError("provisioning profile destination MUST be a regular file")
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    try:
        descriptor = os.open(destination, flags, 0o600)
    except FileExistsError as exc:
        raise ProvisionProfileError(
            f"provisioning profile already exists at {destination}; use --force to replace it"
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(profile.model_dump_json(indent=2))
            stream.write("\n")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    destination.chmod(0o600)
    return ProvisionProfileResult(
        path=str(destination),
        connectivity=profile.connectivity.value,
        execution_host=profile.execution_host.value,
        transport=profile.transport.value,
        access_method=profile.access_method,
    )


def load_provision_profile(path: Path) -> ProvisioningProfile:
    """Load a regular mode-private provisioning profile."""
    if path.is_symlink() or not path.is_file():
        raise ProvisionProfileError("provisioning profile MUST be a regular file")
    if path.stat().st_mode & 0o077:
        raise ProvisionProfileError("provisioning profile permissions MUST be 0600")
    try:
        return ProvisioningProfile.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise ProvisionProfileError("provisioning profile is invalid or unreadable") from exc


__all__ = [
    "DEFAULT_PROFILE_PATH",
    "PROVISION_PROFILE_RESULT_SCHEMA",
    "PROVISION_PROFILE_SCHEMA",
    "AccessMethod",
    "ProvisionProfileError",
    "ProvisionProfileResult",
    "ProvisioningProfile",
    "TemporaryPublicSsh",
    "initialize_provision_profile",
    "load_provision_profile",
]
