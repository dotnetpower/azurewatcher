"""Signed deployment bundle verification tests."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai.deployment_cli.bundle import BundleVerificationError, verify_deployment_bundle
from fdai.deployment_cli.cli import main


def _bundle(tmp_path: Path, *, min_cli: str = "1.0.0") -> tuple[Path, bytes]:
    root = tmp_path / "bundle"
    (root / "infra").mkdir(parents=True)
    (root / "infra" / "main.tf").write_text("terraform {}\n", encoding="utf-8")
    (root / "sbom.json").write_text('{"components":[]}\n', encoding="utf-8")
    files = {
        "infra/main.tf": hashlib.sha256((root / "infra" / "main.tf").read_bytes()).hexdigest(),
        "sbom.json": hashlib.sha256((root / "sbom.json").read_bytes()).hexdigest(),
    }
    manifest = json.dumps(
        {
            "schema_version": "fdai.deployment.bundle.v1",
            "bundle_version": "1.2.0",
            "release_channel": "stable",
            "min_cli_version": min_cli,
            "max_cli_version": "1.9.0",
            "sbom_path": "sbom.json",
            "files": files,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    (root / "manifest.json").write_bytes(manifest)
    (root / "manifest.json.sig").write_bytes(private_key.sign(manifest))
    return root, public_key


def test_valid_bundle_verifies_all_files_and_signature(tmp_path: Path) -> None:
    root, public_key = _bundle(tmp_path)

    result = verify_deployment_bundle(root, public_key_pem=public_key, cli_version="1.3.0")

    assert result.bundle_version == "1.2.0"
    assert result.release_channel.value == "stable"
    assert result.file_count == 2
    assert result.total_bytes > 0


def test_tampered_file_or_manifest_fails(tmp_path: Path) -> None:
    root, public_key = _bundle(tmp_path)
    (root / "infra" / "main.tf").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(BundleVerificationError, match="digest mismatch"):
        verify_deployment_bundle(root, public_key_pem=public_key, cli_version="1.3.0")

    root, public_key = _bundle(tmp_path / "second")
    (root / "manifest.json").write_bytes((root / "manifest.json").read_bytes() + b" ")
    with pytest.raises(BundleVerificationError, match="signature"):
        verify_deployment_bundle(root, public_key_pem=public_key, cli_version="1.3.0")


def test_extra_file_and_symlink_are_rejected(tmp_path: Path) -> None:
    root, public_key = _bundle(tmp_path)
    (root / "extra.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(BundleVerificationError, match="file set"):
        verify_deployment_bundle(root, public_key_pem=public_key, cli_version="1.3.0")

    root, public_key = _bundle(tmp_path / "second")
    (root / "link").symlink_to(root / "sbom.json")
    with pytest.raises(BundleVerificationError, match="symlink"):
        verify_deployment_bundle(root, public_key_pem=public_key, cli_version="1.3.0")


def test_incompatible_cli_is_rejected(tmp_path: Path) -> None:
    root, public_key = _bundle(tmp_path, min_cli="2.0.0")
    with pytest.raises(BundleVerificationError, match="newer CLI"):
        verify_deployment_bundle(root, public_key_pem=public_key, cli_version="1.3.0")


def test_total_size_cap_is_enforced(tmp_path: Path) -> None:
    root, public_key = _bundle(tmp_path)
    with pytest.raises(BundleVerificationError, match="size cap"):
        verify_deployment_bundle(
            root,
            public_key_pem=public_key,
            cli_version="1.3.0",
            max_total_bytes=1,
        )


def test_cli_bundle_verify_emits_stable_json(tmp_path: Path) -> None:
    root, public_key = _bundle(tmp_path, min_cli="0.0.0")
    key_path = tmp_path / "bundle-public.pem"
    key_path.write_bytes(public_key)
    stdout = io.StringIO()

    exit_code = main(
        [
            "bundle",
            "verify",
            "--bundle",
            str(root),
            "--public-key",
            str(key_path),
            "--output",
            "json",
        ],
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["schema_version"] == "fdai.deployment-cli.bundle-verification.v1"
    assert payload["release_channel"] == "stable"
    assert payload["file_count"] == 2
