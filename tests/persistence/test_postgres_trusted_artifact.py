"""PostgreSQL trusted extension/skill artifact persistence tests."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai.core.supply_chain import (
    TrustedArtifactConflictError,
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
)
from fdai.delivery.persistence.postgres_trusted_artifact import (
    PostgresTrustedArtifactStore,
    PostgresTrustedArtifactStoreConfig,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def _record(artifact_id: str, kind: TrustedArtifactKind) -> TrustedArtifactRecord:
    return TrustedArtifactRecord(
        kind=kind,
        artifact_id=artifact_id,
        version="1.0.0",
        source="publisher.example",
        content_sha256="a" * 64,
        artifact=b"trusted artifact",
        signature=b"s" * 64,
        state=TrustedArtifactState.DISABLED,
        revision=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_config_and_revision_validation() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresTrustedArtifactStoreConfig(dsn="")
    store = PostgresTrustedArtifactStore(
        config=PostgresTrustedArtifactStoreConfig(dsn="postgresql://example")
    )
    with pytest.raises(ValueError, match="expected_revision"):
        import asyncio

        asyncio.run(
            store.put(
                _record("example.skill", TrustedArtifactKind.SKILL),
                expected_revision=1,
            )
        )


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.integration
async def test_artifacts_survive_restart_and_updates_are_revision_cas() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    suffix = uuid.uuid4().hex[:8]
    extension = _record(f"example.extension.{suffix}", TrustedArtifactKind.EXTENSION)
    skill = _record(f"example.skill.{suffix}", TrustedArtifactKind.SKILL)
    config = PostgresTrustedArtifactStoreConfig(dsn=dsn)
    store = PostgresTrustedArtifactStore(config=config)
    assert await store.put(extension, expected_revision=0) == extension
    assert await store.put(skill, expected_revision=0) == skill
    enabled = replace(
        extension,
        state=TrustedArtifactState.ENABLED,
        revision=2,
        updated_at=datetime(2026, 7, 17, 12, 1, tzinfo=UTC),
    )
    assert await store.put(enabled, expected_revision=1) == enabled
    with pytest.raises(TrustedArtifactConflictError):
        await store.put(enabled, expected_revision=1)

    restarted = PostgresTrustedArtifactStore(config=config)
    assert await restarted.get(extension.kind, extension.artifact_id) == enabled
    assert skill in await restarted.list(TrustedArtifactKind.SKILL)
