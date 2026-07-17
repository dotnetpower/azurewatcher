"""Offline public extension authoring kit validation tests."""

from __future__ import annotations

import hashlib
import json
from io import StringIO
from pathlib import Path

import pytest

from fdai.deployment_cli.cli import main
from fdai.deployment_cli.extension_kit import (
    ExtensionKitValidationError,
    validate_extension_kit,
)


def _files(tmp_path: Path, *, security_override: dict[str, bool] | None = None):
    archive = tmp_path / "extension.zip"
    archive.write_bytes(b"synthetic extension archive")
    security = {
        "dynamic_code": False,
        "embedded_credentials": False,
        "direct_executor": False,
        "network_installer": False,
        "default_enforce": False,
    }
    security.update(security_override or {})
    manifest = tmp_path / "extension-kit.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "extension": {
                    "extension_id": "example.inspect",
                    "version": "1.0.0",
                    "source": "source:example.inspect",
                    "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "min_host_version": "1.0.0",
                    "max_host_version": "2.0.0",
                    "capability_ids": ["example.inspect"],
                    "enabled": False,
                },
                "security_review": security,
            }
        ),
        encoding="utf-8",
    )
    return manifest, archive


def test_valid_kit_passes_offline_schema_digest_compatibility_and_security(tmp_path: Path) -> None:
    manifest, archive = _files(tmp_path)

    result = validate_extension_kit(manifest, archive, host_version="1.5.0")

    assert result.extension_id == "example.inspect"
    assert result.capability_count == 1


def test_security_or_compatibility_failure_is_rejected(tmp_path: Path) -> None:
    unsafe, archive = _files(tmp_path, security_override={"direct_executor": True})
    with pytest.raises(ExtensionKitValidationError, match="schema"):
        validate_extension_kit(unsafe, archive, host_version="1.5.0")

    manifest, archive = _files(tmp_path)
    with pytest.raises(ExtensionKitValidationError, match="newer"):
        validate_extension_kit(manifest, archive, host_version="0.9.0")


def test_cli_returns_machine_readable_validation_result(tmp_path: Path) -> None:
    manifest, archive = _files(tmp_path)
    output = StringIO()

    exit_code = main(
        [
            "extension",
            "validate",
            "--manifest",
            str(manifest),
            "--archive",
            str(archive),
            "--host-version",
            "1.5.0",
            "--output",
            "json",
        ],
        stdout=output,
    )

    assert exit_code == 0
    assert json.loads(output.getvalue())["extension_id"] == "example.inspect"
