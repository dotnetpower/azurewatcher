"""Tests for selected provisioning profile persistence."""

from __future__ import annotations

import io
import json
import stat
from pathlib import Path

import pytest

from fdai.deployment_cli.cli import main
from fdai.deployment_cli.provision_inspect import (
    Connectivity,
    ExecutionHost,
    ExecutionTransport,
)
from fdai.deployment_cli.provision_profile import (
    ProvisioningProfile,
    ProvisionProfileError,
    TemporaryPublicSsh,
    initialize_provision_profile,
    load_provision_profile,
)


def test_initializes_private_existing_host_profile(tmp_path: Path) -> None:
    destination = tmp_path / "config" / "profile.json"

    result = initialize_provision_profile(
        connectivity=Connectivity.ONLINE,
        execution_host=ExecutionHost.EXISTING,
        transport=ExecutionTransport.MANUAL,
        access_method="internal_ssh",
        destination=destination,
    )

    profile = load_provision_profile(destination)
    assert result.mutation_performed is False
    assert profile.required_human_approvers == 1
    assert profile.require_distinct_executor_identity is True
    assert profile.managed_vm_lifecycle == "persistent_deallocated"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700


def test_offline_profile_requires_artifact_source() -> None:
    with pytest.raises(ValueError, match="artifact_source"):
        ProvisioningProfile(
            connectivity=Connectivity.OFFLINE,
            execution_host=ExecutionHost.EXISTING,
            transport=ExecutionTransport.MANUAL,
            access_method="internal_ssh",
        )


def test_profile_rejects_unresolved_auto_values() -> None:
    with pytest.raises(ValueError, match="connectivity MUST be explicitly"):
        ProvisioningProfile(
            connectivity=Connectivity.AUTO,
            execution_host=ExecutionHost.EXISTING,
            transport=ExecutionTransport.MANUAL,
            access_method="internal_ssh",
        )


@pytest.mark.parametrize("source_cidr", ("0.0.0.0/0", "::/0"))
def test_temporary_public_ssh_rejects_open_source(source_cidr: str) -> None:
    with pytest.raises(ValueError, match="entire address space"):
        TemporaryPublicSsh(source_cidr=source_cidr)


def test_temporary_public_ssh_requires_bounded_settings() -> None:
    with pytest.raises(ValueError, match="bounded access settings"):
        ProvisioningProfile(
            connectivity=Connectivity.ONLINE,
            execution_host=ExecutionHost.MANAGED_VM,
            transport=ExecutionTransport.MANUAL,
            access_method="temporary_public_ssh",
        )


def test_github_transport_and_access_must_match() -> None:
    with pytest.raises(ValueError, match="requires github_actions access"):
        ProvisioningProfile(
            connectivity=Connectivity.ONLINE,
            execution_host=ExecutionHost.MANAGED_VM,
            transport=ExecutionTransport.GITHUB_ACTIONS,
            access_method="internal_ssh",
        )


def test_profile_refuses_overwrite_without_force(tmp_path: Path) -> None:
    destination = tmp_path / "profile.json"
    destination.write_text("existing", encoding="utf-8")

    with pytest.raises(ProvisionProfileError, match="already exists"):
        initialize_provision_profile(
            connectivity=Connectivity.ONLINE,
            execution_host=ExecutionHost.EXISTING,
            transport=ExecutionTransport.MANUAL,
            access_method="internal_ssh",
            destination=destination,
        )

    assert destination.read_text(encoding="utf-8") == "existing"


def test_profile_force_never_follows_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("keep", encoding="utf-8")
    destination = tmp_path / "profile.json"
    destination.symlink_to(target)

    with pytest.raises(ProvisionProfileError, match="regular file"):
        initialize_provision_profile(
            connectivity=Connectivity.ONLINE,
            execution_host=ExecutionHost.EXISTING,
            transport=ExecutionTransport.MANUAL,
            access_method="internal_ssh",
            destination=destination,
            force=True,
        )

    assert target.read_text(encoding="utf-8") == "keep"


def test_cli_init_emits_stable_json(tmp_path: Path) -> None:
    destination = tmp_path / "profile.json"
    stdout = io.StringIO()

    exit_code = main(
        [
            "provision",
            "init",
            "--connectivity",
            "online",
            "--host",
            "existing-host",
            "--transport",
            "manual",
            "--access-method",
            "internal_ssh",
            "--config",
            str(destination),
            "--output",
            "json",
        ],
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["schema_version"] == "fdai.deployment-cli.provision-profile.v1"
    assert payload["mutation_performed"] is False
    assert payload["path"] == str(destination)


def test_cli_init_reports_invalid_profile_without_writing(tmp_path: Path) -> None:
    destination = tmp_path / "profile.json"
    stdout = io.StringIO()

    exit_code = main(
        [
            "provision",
            "init",
            "--connectivity",
            "offline",
            "--host",
            "existing-host",
            "--transport",
            "manual",
            "--access-method",
            "internal_ssh",
            "--config",
            str(destination),
            "--output",
            "json",
        ],
        stdout=stdout,
    )

    assert exit_code == 4
    assert json.loads(stdout.getvalue())["schema_version"] == (
        "fdai.deployment-cli.provision-profile.v1"
    )
    assert not destination.exists()
