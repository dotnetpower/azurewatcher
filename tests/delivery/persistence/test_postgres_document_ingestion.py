"""PostgreSQL integration tests for durable document-ingestion metadata."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from fdai.delivery.persistence.postgres_document_ingestion import (
    PostgresDocumentMetadataStore,
    PostgresDocumentMetadataStoreConfig,
)
from fdai.shared.contracts import (
    AccessDescriptor,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    RetentionPolicy,
    SourceStorageMode,
    UploadSession,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _records(*, document_id=None, active: bool = False):
    now = datetime.now(tz=UTC)
    upload_id = uuid4()
    resolved_document_id = document_id or uuid4()
    version_id = uuid4()
    access = AccessDescriptor(reference="collection:test", collection_id="test")
    retention = RetentionPolicy(policy_version="test-v1")
    session = UploadSession(
        upload_id=upload_id,
        document_id=resolved_document_id,
        version_id=version_id,
        actor_id="integration-test",
        source_name="test.txt",
        collection_id="test",
        object_key=f"quarantine/{upload_id.hex}",
        media_type_hint="text/plain",
        expected_size=4,
        expected_sha256="a" * 64,
        state=DocumentState.UPLOADING,
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        access=access,
        retention=retention,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    version = DocumentVersion(
        document_id=resolved_document_id,
        version_id=version_id,
        upload_id=upload_id,
        source_name="test.txt",
        source_sha256="a" * 64,
        size_bytes=4,
        media_type="text/plain",
        state=DocumentState.UPLOADING,
        access=access,
        retention=retention,
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        uploader_id="integration-test",
        created_at=now,
        updated_at=now,
        active=active,
    )
    return session, version


def test_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresDocumentMetadataStoreConfig(dsn="")


@pytest.mark.integration
async def test_live_metadata_crud_and_active_version_replacement() -> None:
    database_url = os.environ.get("FDAI_DATABASE_URL")
    if not database_url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    upgraded = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert upgraded.returncode == 0, upgraded.stderr
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    store = PostgresDocumentMetadataStore(config=PostgresDocumentMetadataStoreConfig(dsn=dsn))
    first_session, first_version = _records(active=True)
    second_session, second_version = _records(document_id=first_session.document_id, active=True)

    try:
        await store.create(first_session, first_version)
        await store.create(second_session, second_version.model_copy(update={"active": False}))
        promoted_session = first_session.model_copy(
            update={"state": DocumentState.RECEIVED, "object_key": "governed/source"}
        )
        await store.save_upload(promoted_session)
        await store.save_version(second_version)

        assert await store.get_upload(first_session.upload_id) == promoted_session
        persisted_first = await store.get_version(
            first_version.document_id, first_version.version_id
        )
        persisted_second = await store.get_version(
            second_version.document_id, second_version.version_id
        )
        assert persisted_first.active is False
        assert persisted_second == second_version
        versions = await store.list_versions(first_session.document_id)
        assert [version.version_id for version in versions] == [
            first_version.version_id,
            second_version.version_id,
        ]
    finally:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "DELETE FROM document_version WHERE document_id = %s",
                (first_session.document_id,),
            )
            await connection.execute(
                "DELETE FROM document_upload_session WHERE document_id = %s",
                (first_session.document_id,),
            )
