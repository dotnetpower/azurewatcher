"""Signed release-channel upgrade and rollback tests."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai.deployment_cli.bundle import ReleaseChannel
from fdai.deployment_cli.cli import main
from fdai.deployment_cli.release_channels import (
    ReleaseStateError,
    rollback_release,
    upgrade_release,
)


def _key_pair() -> tuple[Ed25519PrivateKey, bytes]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_key


def _bundle(
    root: Path,
    *,
    private_key: Ed25519PrivateKey,
    version: str,
    channel: ReleaseChannel,
    min_cli_version: str = "1.0.0",
) -> Path:
    root.mkdir(parents=True)
    payload = root / "payload.txt"
    payload.write_text(f"bundle-{version}-{channel.value}\n", encoding="utf-8")
    sbom = root / "sbom.cdx.json"
    sbom.write_text('{"bomFormat":"CycloneDX"}\n', encoding="utf-8")
    files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (payload, sbom)}
    manifest = json.dumps(
        {
            "schema_version": "fdai.deployment.bundle.v1",
            "bundle_version": version,
            "release_channel": channel.value,
            "min_cli_version": min_cli_version,
            "max_cli_version": "1.9.0",
            "sbom_path": sbom.name,
            "files": files,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    (root / "manifest.json").write_bytes(manifest)
    (root / "manifest.json.sig").write_bytes(private_key.sign(manifest))
    return root


def test_upgrade_preserves_config_and_records_history(tmp_path: Path) -> None:
    private_key, public_key = _key_pair()
    config = tmp_path / "environment.json"
    config.write_bytes(b'{"environment":"dev","reference":"secret-ref"}\n')
    original_config = config.read_bytes()
    state_path = tmp_path / "state" / "release.json"
    first = _bundle(
        tmp_path / "bundle-1",
        private_key=private_key,
        version="1.0.0",
        channel=ReleaseChannel.STABLE,
    )
    second = _bundle(
        tmp_path / "bundle-2",
        private_key=private_key,
        version="1.1.0",
        channel=ReleaseChannel.STABLE,
    )

    upgrade_release(
        state_path=state_path,
        config_path=config,
        bundle_path=first,
        public_key_pem=public_key,
        cli_version="1.3.0",
        channel=ReleaseChannel.STABLE,
    )
    state = upgrade_release(
        state_path=state_path,
        config_path=config,
        bundle_path=second,
        public_key_pem=public_key,
        cli_version="1.3.0",
        channel=ReleaseChannel.STABLE,
    )

    assert state.active.bundle_version == "1.1.0"
    assert [revision.bundle_version for revision in state.history] == ["1.0.0"]
    assert config.read_bytes() == original_config
    assert state_path.stat().st_mode & 0o777 == 0o600
    assert "secret-ref" not in state_path.read_text(encoding="utf-8")


def test_upgrade_rejects_channel_mismatch_and_version_regression(tmp_path: Path) -> None:
    private_key, public_key = _key_pair()
    config = tmp_path / "environment.json"
    config.write_text("{}\n", encoding="utf-8")
    state_path = tmp_path / "release.json"
    stable = _bundle(
        tmp_path / "stable",
        private_key=private_key,
        version="1.1.0",
        channel=ReleaseChannel.STABLE,
    )
    beta = _bundle(
        tmp_path / "beta",
        private_key=private_key,
        version="1.2.0",
        channel=ReleaseChannel.BETA,
    )
    older = _bundle(
        tmp_path / "older",
        private_key=private_key,
        version="1.0.0",
        channel=ReleaseChannel.STABLE,
    )
    upgrade_release(
        state_path=state_path,
        config_path=config,
        bundle_path=stable,
        public_key_pem=public_key,
        cli_version="1.3.0",
        channel=ReleaseChannel.STABLE,
    )

    with pytest.raises(ReleaseStateError, match="channel"):
        upgrade_release(
            state_path=state_path,
            config_path=config,
            bundle_path=beta,
            public_key_pem=public_key,
            cli_version="1.3.0",
            channel=ReleaseChannel.STABLE,
        )
    with pytest.raises(ReleaseStateError, match="newer"):
        upgrade_release(
            state_path=state_path,
            config_path=config,
            bundle_path=older,
            public_key_pem=public_key,
            cli_version="1.3.0",
            channel=ReleaseChannel.STABLE,
        )


def test_rollback_requires_exact_signed_history_bundle(tmp_path: Path) -> None:
    private_key, public_key = _key_pair()
    config = tmp_path / "environment.json"
    config.write_text("{}\n", encoding="utf-8")
    original_config = config.read_bytes()
    state_path = tmp_path / "release.json"
    first = _bundle(
        tmp_path / "bundle-1",
        private_key=private_key,
        version="1.0.0",
        channel=ReleaseChannel.DEVELOPMENT,
    )
    second = _bundle(
        tmp_path / "bundle-2",
        private_key=private_key,
        version="1.1.0",
        channel=ReleaseChannel.DEVELOPMENT,
    )
    wrong = _bundle(
        tmp_path / "wrong",
        private_key=private_key,
        version="0.9.0",
        channel=ReleaseChannel.DEVELOPMENT,
    )
    for bundle in (first, second):
        upgrade_release(
            state_path=state_path,
            config_path=config,
            bundle_path=bundle,
            public_key_pem=public_key,
            cli_version="1.3.0",
            channel=ReleaseChannel.DEVELOPMENT,
        )

    with pytest.raises(ReleaseStateError, match="history"):
        rollback_release(
            state_path=state_path,
            config_path=config,
            bundle_path=wrong,
            public_key_pem=public_key,
            cli_version="1.3.0",
        )
    state = rollback_release(
        state_path=state_path,
        config_path=config,
        bundle_path=first,
        public_key_pem=public_key,
        cli_version="1.3.0",
    )

    assert state.active.bundle_version == "1.0.0"
    assert state.history == ()
    assert config.read_bytes() == original_config


def test_incompatible_cli_bundle_is_rejected_before_state_write(tmp_path: Path) -> None:
    private_key, public_key = _key_pair()
    config = tmp_path / "environment.json"
    config.write_text("{}\n", encoding="utf-8")
    bundle = _bundle(
        tmp_path / "bundle",
        private_key=private_key,
        version="2.0.0",
        channel=ReleaseChannel.STABLE,
        min_cli_version="2.0.0",
    )
    state_path = tmp_path / "release.json"

    with pytest.raises(ReleaseStateError, match="verification"):
        upgrade_release(
            state_path=state_path,
            config_path=config,
            bundle_path=bundle,
            public_key_pem=public_key,
            cli_version="1.3.0",
            channel=ReleaseChannel.STABLE,
        )

    assert not state_path.exists()


def test_cli_upgrade_emits_stable_release_json(tmp_path: Path) -> None:
    private_key, public_key = _key_pair()
    config = tmp_path / "environment.json"
    config.write_text("{}\n", encoding="utf-8")
    bundle = _bundle(
        tmp_path / "bundle",
        private_key=private_key,
        version="1.0.0",
        channel=ReleaseChannel.BETA,
        min_cli_version="0.0.0",
    )
    public_key_path = tmp_path / "public.pem"
    public_key_path.write_bytes(public_key)
    stdout = io.StringIO()

    exit_code = main(
        [
            "release",
            "upgrade",
            "--state",
            str(tmp_path / "release.json"),
            "--config",
            str(config),
            "--bundle",
            str(bundle),
            "--public-key",
            str(public_key_path),
            "--channel",
            "beta",
            "--output",
            "json",
        ],
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["schema_version"] == "fdai.deployment-cli.release-result.v1"
    assert payload["operation"] == "upgrade"
    assert payload["active"]["release_channel"] == "beta"
