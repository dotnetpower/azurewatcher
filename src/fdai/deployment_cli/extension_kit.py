"""Offline validation for public FDAI extension authoring kits."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from fdai.core.capability_catalog import ExtensionManifest

EXTENSION_KIT_SCHEMA_VERSION = "1.0.0"
_EXTENSION_KIT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "extension", "security_review"],
    "properties": {
        "schema_version": {"const": EXTENSION_KIT_SCHEMA_VERSION},
        "extension": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "extension_id",
                "version",
                "source",
                "archive_sha256",
                "min_host_version",
                "max_host_version",
                "capability_ids",
                "enabled",
            ],
            "properties": {
                "extension_id": {"type": "string"},
                "version": {"type": "string"},
                "source": {"type": "string"},
                "archive_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "min_host_version": {"type": "string"},
                "max_host_version": {"type": ["string", "null"]},
                "capability_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "uniqueItems": True,
                    "minItems": 1,
                },
                "enabled": {"const": False},
            },
        },
        "security_review": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "dynamic_code",
                "embedded_credentials",
                "direct_executor",
                "network_installer",
                "default_enforce",
            ],
            "properties": {
                "dynamic_code": {"const": False},
                "embedded_credentials": {"const": False},
                "direct_executor": {"const": False},
                "network_installer": {"const": False},
                "default_enforce": {"const": False},
            },
        },
    },
}


class ExtensionKitValidationError(ValueError):
    """Extension authoring kit failed offline schema or security validation."""


@dataclass(frozen=True, slots=True)
class ExtensionKitValidationResult:
    extension_id: str
    extension_version: str
    host_version: str
    capability_count: int
    archive_sha256: str
    schema_version: str = "fdai.extension-kit-validation.v1"

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def validate_extension_kit(
    manifest_path: Path,
    archive_path: Path,
    *,
    host_version: str,
) -> ExtensionKitValidationResult:
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        archive = archive_path.read_bytes()
    except (OSError, ValueError) as exc:
        raise ExtensionKitValidationError(
            "extension kit files are unreadable or invalid JSON"
        ) from exc
    errors = sorted(Draft202012Validator(_EXTENSION_KIT_SCHEMA).iter_errors(raw), key=str)
    if errors:
        raise ExtensionKitValidationError(f"extension kit schema failed: {errors[0].message}")
    extension = raw["extension"]
    manifest = ExtensionManifest(
        extension_id=extension["extension_id"],
        version=extension["version"],
        source=extension["source"],
        archive_sha256=extension["archive_sha256"],
        min_host_version=extension["min_host_version"],
        max_host_version=extension["max_host_version"],
        capability_ids=tuple(extension["capability_ids"]),
    )
    digest = hashlib.sha256(archive).hexdigest()
    if digest != manifest.archive_sha256:
        raise ExtensionKitValidationError("extension archive digest does not match manifest")
    host = _version_tuple(host_version)
    if host < _version_tuple(manifest.min_host_version):
        raise ExtensionKitValidationError("extension requires a newer FDAI host")
    if manifest.max_host_version is not None and host > _version_tuple(manifest.max_host_version):
        raise ExtensionKitValidationError("extension does not support this FDAI host version")
    return ExtensionKitValidationResult(
        extension_id=manifest.extension_id,
        extension_version=manifest.version,
        host_version=host_version,
        capability_count=len(manifest.capability_ids),
        archive_sha256=digest,
    )


def _version_tuple(value: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise ExtensionKitValidationError("host version MUST use MAJOR.MINOR.PATCH") from exc
    if len(parts) != 3 or any(part < 0 for part in parts):
        raise ExtensionKitValidationError("host version MUST use MAJOR.MINOR.PATCH")
    return parts


__all__ = [
    "EXTENSION_KIT_SCHEMA_VERSION",
    "ExtensionKitValidationError",
    "ExtensionKitValidationResult",
    "validate_extension_kit",
]
