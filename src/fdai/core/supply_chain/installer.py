"""Trust-verify and durably install extensions and skills as disabled artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from fdai.core.capability_catalog.extensions import (
    ExtensionManager,
    ExtensionPackage,
    ExtensionTrustVerifier,
)
from fdai.core.skills.catalog import SkillCatalog, SkillTrustVerifier, parse_skill_markdown
from fdai.core.supply_chain.artifacts import (
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
    TrustedArtifactStore,
)


@dataclass(frozen=True, slots=True)
class TrustedArtifactInstaller:
    """Keep trust verification, disabled-first install, and durability atomic to callers."""

    store: TrustedArtifactStore

    async def install_extension(
        self,
        manager: ExtensionManager,
        package: ExtensionPackage,
        *,
        archive: bytes,
        signature: bytes,
        verifier: ExtensionTrustVerifier,
        now: datetime,
    ) -> ExtensionManager:
        candidate = manager.install(package, archive=archive, verifier=verifier)
        manifest = package.manifest
        await self.store.put(
            TrustedArtifactRecord(
                kind=TrustedArtifactKind.EXTENSION,
                artifact_id=manifest.extension_id,
                version=manifest.version,
                source=manifest.source,
                content_sha256=manifest.archive_sha256,
                artifact=archive,
                signature=signature,
                state=TrustedArtifactState.DISABLED,
                revision=1,
                created_at=now,
                updated_at=now,
            ),
            expected_revision=0,
        )
        return candidate

    async def install_skill(
        self,
        catalog: SkillCatalog,
        raw_markdown: bytes,
        *,
        signature: bytes,
        verifier: SkillTrustVerifier,
        now: datetime,
    ) -> SkillCatalog:
        candidate = catalog.install(raw_markdown, verifier=verifier)
        skill = parse_skill_markdown(raw_markdown)
        await self.store.put(
            TrustedArtifactRecord(
                kind=TrustedArtifactKind.SKILL,
                artifact_id=skill.manifest.name,
                version=skill.manifest.version,
                source=skill.manifest.source,
                content_sha256=hashlib.sha256(raw_markdown).hexdigest(),
                artifact=raw_markdown,
                signature=signature,
                state=TrustedArtifactState.DISABLED,
                revision=1,
                created_at=now,
                updated_at=now,
            ),
            expected_revision=0,
        )
        return candidate
