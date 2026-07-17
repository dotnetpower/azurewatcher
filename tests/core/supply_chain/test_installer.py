"""Trust lifecycle plus durable disabled-first installation tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from fdai.core.capability_catalog import (
    CapabilityBundle,
    CapabilityReferences,
    ExtensionManager,
    ExtensionManifest,
    ExtensionPackage,
)
from fdai.core.skills import SkillCatalog, skill_body_digest
from fdai.core.supply_chain import (
    TrustedArtifactConflictError,
    TrustedArtifactInstaller,
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
)

_NOW = datetime(2026, 7, 17, 13, 0, tzinfo=UTC)


class _Store:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.records: list[TrustedArtifactRecord] = []

    async def put(
        self,
        record: TrustedArtifactRecord,
        *,
        expected_revision: int,
    ) -> TrustedArtifactRecord:
        assert expected_revision == 0
        if self.fail:
            raise TrustedArtifactConflictError("conflict")
        self.records.append(record)
        return record

    async def get(self, kind, artifact_id):  # type: ignore[no-untyped-def]
        del kind, artifact_id
        return None

    async def list(self, kind):  # type: ignore[no-untyped-def]
        del kind
        return tuple(self.records)


class _Allow:
    def verify(self, _value, _raw):  # type: ignore[no-untyped-def]
        return True


def _skill() -> bytes:
    body = "Use deterministic tools only."
    return (
        "---\n"
        "name: example.skill\n"
        "version: 1.0.0\n"
        "description: Example\n"
        "source: publisher.example\n"
        f"body_sha256: {skill_body_digest(body)}\n"
        "required_tools: []\n"
        "allowed_agents: []\n"
        "---\n"
        f"{body}\n"
    ).encode()


async def test_skill_install_persists_raw_disabled_artifact() -> None:
    store = _Store()
    installer = TrustedArtifactInstaller(store=store)
    raw = _skill()

    catalog = await installer.install_skill(
        SkillCatalog(),
        raw,
        signature=b"s" * 64,
        verifier=_Allow(),
        now=_NOW,
    )

    assert catalog.get("example.skill").enabled is False
    assert store.records[0].kind is TrustedArtifactKind.SKILL
    assert store.records[0].state is TrustedArtifactState.DISABLED
    assert store.records[0].artifact == raw


async def test_extension_persistence_failure_does_not_return_candidate() -> None:
    store = _Store(fail=True)
    installer = TrustedArtifactInstaller(store=store)
    archive = b"archive"
    package = ExtensionPackage(
        manifest=ExtensionManifest(
            extension_id="example.extension",
            version="1.0.0",
            source="publisher.example",
            archive_sha256=hashlib.sha256(archive).hexdigest(),
            min_host_version="1.0.0",
        ),
        bundle=CapabilityBundle(capabilities=(), bindings=()),
    )
    manager = ExtensionManager(
        host_version="1.0.0",
        references=CapabilityReferences(),
    )

    with pytest.raises(TrustedArtifactConflictError):
        await installer.install_extension(
            manager,
            package,
            archive=archive,
            signature=b"s" * 64,
            verifier=_Allow(),
            now=_NOW,
        )

    assert manager.list() == ()
