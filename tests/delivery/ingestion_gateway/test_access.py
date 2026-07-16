"""Tests for claims-backed governed document access."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from fdai.delivery.ingestion_gateway.access import ClaimsDocumentAccessProvider
from fdai.shared.contracts import (
    AccessDescriptor,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    RetentionPolicy,
)
from fdai.shared.providers.document_ingestion import DocumentAccessDeniedError


def _version() -> DocumentVersion:
    now = datetime(2026, 7, 16, tzinfo=UTC)
    return DocumentVersion(
        document_id=UUID("00000000-0000-0000-0000-000000000501"),
        version_id=UUID("00000000-0000-0000-0000-000000000502"),
        upload_id=UUID("00000000-0000-0000-0000-000000000503"),
        source_name="guide.txt",
        source_sha256="a" * 64,
        size_bytes=1,
        media_type="text/plain",
        state=DocumentState.READY,
        access=AccessDescriptor(
            reference="collection:shared",
            collection_id="shared",
            reader_groups=("reader-group",),
        ),
        retention=RetentionPolicy(policy_version="v1"),
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        uploader_id="uploader",
        created_at=now,
        updated_at=now,
    )


async def test_claims_access_applies_roles_groups_and_uploader_ownership() -> None:
    access = ClaimsDocumentAccessProvider()
    version = _version()

    await access.authorize_create(
        actor_id="contributor",
        actor_groups=frozenset({"role:Contributor"}),
        collection_id="shared",
    )
    await access.authorize_read(
        actor_id="reader",
        actor_groups=frozenset({"reader-group"}),
        version=version,
    )
    await access.authorize_delete(
        actor_id="uploader",
        actor_groups=frozenset(),
        version=version,
    )
    await access.authorize_delete(
        actor_id="owner",
        actor_groups=frozenset({"role:Owner"}),
        version=version,
    )

    with pytest.raises(DocumentAccessDeniedError):
        await access.authorize_read(
            actor_id="other",
            actor_groups=frozenset({"unrelated-group"}),
            version=version,
        )
