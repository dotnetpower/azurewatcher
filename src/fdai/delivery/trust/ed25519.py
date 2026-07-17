"""Domain-separated Ed25519 verification for extensions and skills."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from fdai.core.capability_catalog.extensions import ExtensionManifest
from fdai.core.skills.catalog import RuntimeSkill


@dataclass(frozen=True, slots=True)
class Ed25519ExtensionTrustVerifier:
    """Verify one detached extension signature against a publisher registry."""

    trusted_publishers: Mapping[str, bytes]
    signature: bytes

    def verify(self, manifest: ExtensionManifest, archive: bytes) -> bool:
        if hashlib.sha256(archive).hexdigest() != manifest.archive_sha256:
            return False
        return _verify(
            self.trusted_publishers.get(manifest.source),
            self.signature,
            extension_signature_payload(manifest),
        )


@dataclass(frozen=True, slots=True)
class Ed25519SkillTrustVerifier:
    """Verify one detached skill signature against a publisher registry."""

    trusted_publishers: Mapping[str, bytes]
    signature: bytes

    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return _verify(
            self.trusted_publishers.get(skill.manifest.source),
            self.signature,
            skill_signature_payload(skill, raw_markdown),
        )


@dataclass(frozen=True, slots=True)
class Ed25519ModelEndpointRegistrationVerifier:
    """Verify signed self-hosted model endpoint registration bytes."""

    trusted_publishers: Mapping[str, bytes]

    def verify(self, *, source: str, document: bytes, signature: bytes) -> bool:
        return _verify(
            self.trusted_publishers.get(source),
            signature,
            model_endpoint_registration_signature_payload(source, document),
        )


def extension_signature_payload(manifest: ExtensionManifest) -> bytes:
    """Canonical domain-separated extension signature payload."""
    return _payload(
        "fdai.extension-signature.v1",
        manifest.source,
        manifest.extension_id,
        manifest.version,
        manifest.archive_sha256,
    )


def skill_signature_payload(skill: RuntimeSkill, raw_markdown: bytes) -> bytes:
    """Canonical domain-separated skill signature payload."""
    return _payload(
        "fdai.skill-signature.v1",
        skill.manifest.source,
        skill.manifest.name,
        skill.manifest.version,
        hashlib.sha256(raw_markdown).hexdigest(),
    )


def model_endpoint_registration_signature_payload(source: str, document: bytes) -> bytes:
    """Canonical domain-separated payload for a self-hosted endpoint record."""
    return _payload(
        "fdai.model-endpoint-registration.v1",
        source,
        hashlib.sha256(document).hexdigest(),
    )


def _payload(*parts: str) -> bytes:
    if any(not part or "\0" in part for part in parts):
        raise ValueError("signature payload fields MUST be non-empty and NUL-free")
    return "\0".join(parts).encode("utf-8")


def _verify(public_key_pem: bytes | None, signature: bytes, payload: bytes) -> bool:
    if public_key_pem is None or len(signature) != 64:
        return False
    try:
        key = load_pem_public_key(public_key_pem)
        if not isinstance(key, Ed25519PublicKey):
            return False
        key.verify(signature, payload)
    except (InvalidSignature, TypeError, ValueError):
        return False
    return True


__all__ = [
    "Ed25519ExtensionTrustVerifier",
    "Ed25519ModelEndpointRegistrationVerifier",
    "Ed25519SkillTrustVerifier",
    "extension_signature_payload",
    "model_endpoint_registration_signature_payload",
    "skill_signature_payload",
]
