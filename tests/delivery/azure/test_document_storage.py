"""Offline tests for ADLS Gen2 governed document storage adapters."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from fdai.delivery.azure.document_storage import (
    AzureDataLakeArtifactStore,
    AzureDataLakeConfig,
    AzureDataLakeObjectStore,
    WorkloadIdentityTokenCredential,
)
from fdai.shared.contracts import (
    AccessDescriptor,
    DocumentEnvelope,
    DocumentPurpose,
    DocumentState,
    ProtectionState,
    RetentionPolicy,
    SourceStorageMode,
    StructuralUnit,
    UploadSession,
)
from fdai.shared.providers.workload_identity import IdentityToken

_UPLOAD_ID = UUID("00000000-0000-0000-0000-000000000301")
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000302")
_VERSION_ID = UUID("00000000-0000-0000-0000-000000000303")


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",
            audience=audience,
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
        )


class _Download:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def chunks(self) -> AsyncIterator[bytes]:
        yield self._data[:3]
        yield self._data[3:]


class _File:
    def __init__(self, path: str) -> None:
        self.path = path
        self.data = b""
        self.metadata: dict[str, str] = {}
        self.deleted = False
        self.renamed_to: str | None = None

    async def upload_data(self, data: Any, **_kwargs: Any) -> dict[str, str]:
        if hasattr(data, "__aiter__"):
            content = bytearray()
            async for chunk in data:
                content.extend(chunk)
            self.data = bytes(content)
        else:
            self.data = bytes(data)
        metadata = _kwargs.get("metadata")
        if isinstance(metadata, dict):
            self.metadata = {str(key): str(value) for key, value in metadata.items()}
        return {}

    async def set_metadata(self, metadata: dict[str, str], **_kwargs: Any) -> dict[str, str]:
        self.metadata = dict(metadata)
        return {}

    async def get_file_properties(self, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(size=len(self.data), metadata=self.metadata)

    async def download_file(self, **_kwargs: Any) -> _Download:
        return _Download(self.data)

    async def delete_file(self, **_kwargs: Any) -> None:
        self.deleted = True

    async def rename_file(self, new_name: str, **_kwargs: Any) -> _File:
        self.renamed_to = new_name
        return self


class _FileSystem:
    def __init__(self) -> None:
        self.files: dict[str, _File] = {}

    def get_file_client(self, path: str) -> _File:
        return self.files.setdefault(path, _File(path))


class _Service:
    def __init__(self) -> None:
        self.file_systems: dict[str, _FileSystem] = {}
        self.closed = False

    def get_file_system_client(self, name: str) -> _FileSystem:
        return self.file_systems.setdefault(name, _FileSystem())

    async def close(self) -> None:
        self.closed = True


def _config() -> AzureDataLakeConfig:
    return AzureDataLakeConfig(
        account_name="stfdaidocdev",
        account_url="https://stfdaidocdev.dfs.core.windows.net",
    )


def _session() -> UploadSession:
    now = datetime(2026, 7, 16, tzinfo=UTC)
    return UploadSession(
        upload_id=_UPLOAD_ID,
        document_id=_DOCUMENT_ID,
        version_id=_VERSION_ID,
        actor_id="actor",
        source_name="guide.txt",
        collection_id="shared-knowledge",
        object_key=f"quarantine/{_UPLOAD_ID.hex}",
        media_type_hint="text/plain",
        expected_size=7,
        expected_sha256=hashlib.sha256(b"content").hexdigest(),
        state=DocumentState.UPLOADING,
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        access=AccessDescriptor(
            reference="collection:shared-knowledge",
            collection_id="shared-knowledge",
        ),
        retention=RetentionPolicy(policy_version="policy-v1"),
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )


def _envelope() -> DocumentEnvelope:
    return DocumentEnvelope(
        document_id=_DOCUMENT_ID,
        version_id=_VERSION_ID,
        source_sha256="a" * 64,
        media_type="text/plain",
        observed_format="text",
        size_bytes=7,
        collection_id="shared-knowledge",
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        protection_state=ProtectionState.NONE,
        access_descriptor_ref="collection:shared-knowledge",
        units=(StructuralUnit(unit_id="line-1", kind="text", locator="line:1", text="content"),),
        extractor_name="test",
        extractor_version="1.0.0",
    )


async def _chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


async def test_workload_identity_credential_adapts_storage_scope() -> None:
    credential = WorkloadIdentityTokenCredential(_Identity())
    token = await credential.get_token("https://storage.azure.com/.default")

    assert token.token == "test-token"
    with pytest.raises(ValueError, match="Azure Storage scope"):
        await credential.get_token("https://management.azure.com/.default")


async def test_object_store_streams_hashes_reads_and_promotes() -> None:
    service = _Service()
    store = AzureDataLakeObjectStore(
        config=_config(),
        service_client=cast(Any, service),
    )
    session = _session()

    info = await store.put_stream(
        session.object_key,
        _chunks(b"con", b"tent"),
        expected_size=7,
        max_size=10,
    )
    stat = await store.stat(session.object_key)
    content = b"".join([chunk async for chunk in store.read(session.object_key)])
    promoted = await store.promote(session)

    assert info == stat
    assert info.sha256 == hashlib.sha256(b"content").hexdigest()
    assert content == b"content"
    collection = hashlib.sha256(b"shared-knowledge").hexdigest()[:16]
    assert promoted == f"governed/{collection}/{_DOCUMENT_ID.hex}/{_VERSION_ID.hex}/source"
    source = service.file_systems["documents"].files[session.object_key]
    assert source.renamed_to == f"documents/{promoted}"


async def test_object_store_deletes_partial_oversized_upload() -> None:
    service = _Service()
    store = AzureDataLakeObjectStore(config=_config(), service_client=cast(Any, service))
    key = "quarantine/oversized"

    with pytest.raises(ValueError, match="exceeds"):
        await store.put_stream(key, _chunks(b"12345", b"67890"), expected_size=8, max_size=8)

    assert service.file_systems["documents"].files[key].deleted is True


async def test_artifact_store_persists_and_deletes_envelope() -> None:
    service = _Service()
    store = AzureDataLakeArtifactStore(config=_config(), service_client=cast(Any, service))

    uri = await store.put(_envelope())
    await store.delete(_DOCUMENT_ID, _VERSION_ID)

    path = f"documents/{_DOCUMENT_ID.hex}/versions/{_VERSION_ID.hex}/envelope.json"
    artifact = service.file_systems["derived"].files[path]
    assert uri.endswith(f"/derived/{path}")
    assert b'"collection_id":"shared-knowledge"' in artifact.data
    assert artifact.deleted is True
