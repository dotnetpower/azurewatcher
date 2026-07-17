"""Concrete extension and skill Ed25519 trust verification tests."""

from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai.core.capability_catalog.extensions import ExtensionManifest
from fdai.core.skills.catalog import RuntimeSkill, parse_skill_markdown, skill_body_digest
from fdai.delivery.trust.ed25519 import (
    Ed25519ExtensionTrustVerifier,
    Ed25519SkillTrustVerifier,
    extension_signature_payload,
    skill_signature_payload,
)


def _keys() -> tuple[Ed25519PrivateKey, bytes]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, public


def _extension(archive: bytes, *, source: str = "publisher.example") -> ExtensionManifest:
    return ExtensionManifest(
        extension_id="example.extension",
        version="1.2.3",
        source=source,
        archive_sha256=hashlib.sha256(archive).hexdigest(),
        min_host_version="1.0.0",
    )


def _skill(*, source: str = "publisher.example") -> tuple[RuntimeSkill, bytes]:
    body = "Use deterministic tools only."
    raw = (
        "---\n"
        "name: example.skill\n"
        "version: 1.2.3\n"
        "description: Example\n"
        f"source: {source}\n"
        f"body_sha256: {skill_body_digest(body)}\n"
        "required_tools: []\n"
        "allowed_agents: []\n"
        "---\n"
        f"{body}\n"
    ).encode()
    return parse_skill_markdown(raw), raw


def test_extension_signature_verifies_and_rejects_replay() -> None:
    private, public = _keys()
    archive = b"extension archive"
    manifest = _extension(archive)
    signature = private.sign(extension_signature_payload(manifest))
    verifier = Ed25519ExtensionTrustVerifier(
        trusted_publishers={manifest.source: public},
        signature=signature,
    )

    assert verifier.verify(manifest, archive) is True
    assert verifier.verify(manifest, b"changed") is False
    assert verifier.verify(_extension(archive, source="other.publisher"), archive) is False


def test_skill_signature_verifies_full_markdown_and_rejects_cross_kind() -> None:
    private, public = _keys()
    skill, raw = _skill()
    signature = private.sign(skill_signature_payload(skill, raw))
    verifier = Ed25519SkillTrustVerifier(
        trusted_publishers={skill.manifest.source: public},
        signature=signature,
    )

    assert verifier.verify(skill, raw) is True
    assert verifier.verify(skill, raw + b" ") is False
    extension = _extension(b"archive")
    assert signature != private.sign(extension_signature_payload(extension))


def test_non_ed25519_key_and_invalid_signature_fail_closed() -> None:
    _private, public = _keys()
    skill, raw = _skill()
    verifier = Ed25519SkillTrustVerifier(
        trusted_publishers={skill.manifest.source: public},
        signature=b"short",
    )

    assert verifier.verify(skill, raw) is False
