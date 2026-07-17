"""Signed release-channel upgrade and rollback state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fdai.deployment_cli.bundle import (
    BundleVerification,
    BundleVerificationError,
    ReleaseChannel,
    verify_deployment_bundle,
)

RELEASE_STATE_SCHEMA: Final = "fdai.deployment.release-state.v1"
RELEASE_RESULT_SCHEMA: Final = "fdai.deployment-cli.release-result.v1"
_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_MAX_CONFIG_BYTES: Final = 4 * 1024 * 1024
_MAX_STATE_BYTES: Final = 64 * 1024
_MAX_HISTORY: Final = 20


class _ReleaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReleaseRevision(_ReleaseModel):
    bundle_version: str
    release_channel: ReleaseChannel
    manifest_digest: str

    def model_post_init(self, __context: object) -> None:
        _version_tuple(self.bundle_version)
        if _DIGEST.fullmatch(self.manifest_digest) is None:
            raise ValueError("release manifest_digest MUST be a lowercase SHA-256 digest")


class ReleaseState(_ReleaseModel):
    schema_version: Literal["fdai.deployment.release-state.v1"] = RELEASE_STATE_SCHEMA
    active: ReleaseRevision
    history: tuple[ReleaseRevision, ...] = Field(default=(), max_length=_MAX_HISTORY)
    config_digest: str

    def model_post_init(self, __context: object) -> None:
        if _DIGEST.fullmatch(self.config_digest) is None:
            raise ValueError("release config_digest MUST be a lowercase SHA-256 digest")

    def to_json(self, *, operation: str) -> str:
        return json.dumps(
            {
                "active": self.active.model_dump(mode="json"),
                "history_depth": len(self.history),
                "operation": operation,
                "schema_version": RELEASE_RESULT_SCHEMA,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


class ReleaseStateError(RuntimeError):
    """A release pointer transition failed before activation."""


def upgrade_release(
    *,
    state_path: Path,
    config_path: Path,
    bundle_path: Path,
    public_key_pem: bytes,
    cli_version: str,
    channel: ReleaseChannel,
) -> ReleaseState:
    """Verify and atomically activate a forward release revision."""
    config_digest = _guarded_file_digest(config_path, "configuration", _MAX_CONFIG_BYTES)
    verification = _verify(bundle_path, public_key_pem, cli_version)
    if verification.release_channel is not channel:
        raise ReleaseStateError("signed bundle channel does not match the requested channel")
    candidate = _revision(verification)
    current = _load_optional_state(state_path)
    if current is not None:
        if candidate.manifest_digest == current.active.manifest_digest:
            return current
        if _version_tuple(candidate.bundle_version) <= _version_tuple(
            current.active.bundle_version
        ):
            raise ReleaseStateError("upgrade requires a newer bundle version; use rollback")
        history = (current.active, *current.history)[:_MAX_HISTORY]
    else:
        history = ()
    state = ReleaseState(
        active=candidate,
        history=history,
        config_digest=config_digest,
    )
    _write_state_guarded(state_path, state, config_path, config_digest)
    return state


def rollback_release(
    *,
    state_path: Path,
    config_path: Path,
    bundle_path: Path,
    public_key_pem: bytes,
    cli_version: str,
) -> ReleaseState:
    """Verify and atomically restore the newest prior signed revision."""
    config_digest = _guarded_file_digest(config_path, "configuration", _MAX_CONFIG_BYTES)
    current = _load_required_state(state_path)
    if not current.history:
        raise ReleaseStateError("release history is empty")
    target = current.history[0]
    verification = _verify(bundle_path, public_key_pem, cli_version)
    candidate = _revision(verification)
    if candidate != target:
        raise ReleaseStateError("rollback bundle does not match the newest release history entry")
    state = ReleaseState(
        active=target,
        history=current.history[1:],
        config_digest=config_digest,
    )
    _write_state_guarded(state_path, state, config_path, config_digest)
    return state


def _verify(
    bundle_path: Path,
    public_key_pem: bytes,
    cli_version: str,
) -> BundleVerification:
    try:
        return verify_deployment_bundle(
            bundle_path,
            public_key_pem=public_key_pem,
            cli_version=cli_version,
        )
    except (BundleVerificationError, ValueError) as exc:
        raise ReleaseStateError("release bundle verification failed") from exc


def _revision(verification: BundleVerification) -> ReleaseRevision:
    return ReleaseRevision(
        bundle_version=verification.bundle_version,
        release_channel=verification.release_channel,
        manifest_digest=verification.manifest_digest,
    )


def _load_optional_state(path: Path) -> ReleaseState | None:
    if not path.exists():
        return None
    return _load_required_state(path)


def _load_required_state(path: Path) -> ReleaseState:
    if path.is_symlink() or not path.is_file():
        raise ReleaseStateError("release state MUST be a regular file")
    if path.stat().st_size > _MAX_STATE_BYTES:
        raise ReleaseStateError("release state exceeds the size limit")
    try:
        return ReleaseState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        raise ReleaseStateError("release state is invalid or unreadable") from exc


def _write_state_guarded(
    path: Path,
    state: ReleaseState,
    config_path: Path,
    expected_config_digest: str,
) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = state.model_dump_json().encode("utf-8") + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".release-state-", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        current_config_digest = _guarded_file_digest(
            config_path,
            "configuration",
            _MAX_CONFIG_BYTES,
        )
        if current_config_digest != expected_config_digest:
            raise ReleaseStateError("configuration changed during release transition")
        os.replace(temporary_path, path)
        path.chmod(0o600)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _guarded_file_digest(path: Path, label: str, maximum: int) -> str:
    if path.is_symlink() or not path.is_file():
        raise ReleaseStateError(f"{label} MUST be a regular file")
    if path.stat().st_size > maximum:
        raise ReleaseStateError(f"{label} exceeds the size limit")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ReleaseStateError(f"{label} is unreadable") from exc
    return digest.hexdigest()


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value)
    if match is None:
        raise ValueError("release version MUST use MAJOR.MINOR.PATCH")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


__all__ = [
    "RELEASE_RESULT_SCHEMA",
    "RELEASE_STATE_SCHEMA",
    "ReleaseRevision",
    "ReleaseState",
    "ReleaseStateError",
    "rollback_release",
    "upgrade_release",
]
