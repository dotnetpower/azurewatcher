"""ADLS Gen2 adapters for governed document source and derived artifacts."""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from azure.core.credentials import AccessToken
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.filedatalake.aio import DataLakeServiceClient

from fdai.shared.contracts import DocumentEnvelope, UploadSession
from fdai.shared.providers.document_ingestion import (
    DocumentNotFoundError,
    ProviderUnavailableError,
    StoredObjectInfo,
    UploadGrant,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_STORAGE_SCOPE: Final[str] = "https://storage.azure.com/.default"
_FILESYSTEM_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?")


@dataclass(frozen=True, slots=True)
class AzureDataLakeConfig:
    account_name: str
    account_url: str
    source_file_system: str = "documents"
    derived_file_system: str = "derived"
    operation_timeout_seconds: int = 60

    def __post_init__(self) -> None:
        if not self.account_name or not self.account_url.startswith("https://"):
            raise ValueError("ADLS account_name and HTTPS account_url are required")
        for name in (self.source_file_system, self.derived_file_system):
            if not _FILESYSTEM_RE.fullmatch(name):
                raise ValueError("ADLS file-system names MUST be valid lowercase container names")
        if self.operation_timeout_seconds < 1:
            raise ValueError("operation_timeout_seconds MUST be positive")


class WorkloadIdentityTokenCredential:
    """Adapt FDAI's WorkloadIdentity seam to the Azure SDK async credential contract."""

    def __init__(self, identity: WorkloadIdentity) -> None:
        self._identity = identity

    async def get_token(self, *scopes: str, **_kwargs: Any) -> AccessToken:
        if len(scopes) != 1 or scopes[0] != _STORAGE_SCOPE:
            raise ValueError("ADLS credential accepts only the Azure Storage scope")
        token = await self._identity.get_token(_STORAGE_SCOPE)
        return AccessToken(token.token, int(token.expires_at.timestamp()))

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> WorkloadIdentityTokenCredential:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()


class AzureDataLakeObjectStore:
    """Stream source bytes into private ADLS and atomically promote accepted versions."""

    def __init__(
        self,
        *,
        config: AzureDataLakeConfig,
        service_client: DataLakeServiceClient,
    ) -> None:
        self._config = config
        self._service = service_client
        self._files = service_client.get_file_system_client(config.source_file_system)

    @classmethod
    def from_identity(
        cls,
        *,
        config: AzureDataLakeConfig,
        identity: WorkloadIdentity,
    ) -> AzureDataLakeObjectStore:
        credential = WorkloadIdentityTokenCredential(identity)
        service = DataLakeServiceClient(account_url=config.account_url, credential=credential)
        return cls(config=config, service_client=service)

    async def issue_upload(self, session: UploadSession) -> UploadGrant:
        return UploadGrant(
            upload_id=session.upload_id,
            target=f"adls://{self._config.source_file_system}/{session.object_key}",
            expires_at=session.expires_at,
        )

    async def resume_upload(self, session: UploadSession) -> UploadGrant:
        return await self.issue_upload(session)

    async def put_stream(
        self,
        object_key: str,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int,
        max_size: int,
    ) -> StoredObjectInfo:
        file_client = self._files.get_file_client(object_key)
        digest = hashlib.sha256()
        observed_size = 0

        async def tracked() -> AsyncIterator[bytes]:
            nonlocal observed_size
            async for chunk in chunks:
                observed_size += len(chunk)
                if observed_size > max_size or observed_size > expected_size:
                    raise ValueError("streamed content exceeds the upload-session limit")
                digest.update(chunk)
                yield chunk

        try:
            await file_client.upload_data(
                tracked(),
                length=expected_size,
                overwrite=True,
                timeout=self._config.operation_timeout_seconds,
                max_concurrency=1,
            )
            if observed_size != expected_size:
                raise ValueError("streamed content size does not match the upload session")
            sha256 = digest.hexdigest()
            await file_client.set_metadata(
                {"fdai_sha256": sha256, "fdai_size": str(observed_size)},
                timeout=self._config.operation_timeout_seconds,
            )
            return StoredObjectInfo(object_key, observed_size, sha256)
        except Exception:
            try:
                await file_client.delete_file(timeout=self._config.operation_timeout_seconds)
            except ResourceNotFoundError:
                pass
            raise

    async def stat(self, object_key: str) -> StoredObjectInfo:
        file_client = self._files.get_file_client(object_key)
        try:
            properties = await file_client.get_file_properties(
                timeout=self._config.operation_timeout_seconds
            )
        except ResourceNotFoundError as exc:
            raise DocumentNotFoundError("source object was not found") from exc
        metadata = properties.metadata or {}
        sha256 = metadata.get("fdai_sha256")
        if not isinstance(sha256, str) or len(sha256) != 64:
            raise ProviderUnavailableError("source object hash metadata is unavailable")
        return StoredObjectInfo(object_key, int(properties.size), sha256)

    async def read(self, object_key: str) -> AsyncIterator[bytes]:
        file_client = self._files.get_file_client(object_key)
        try:
            download = await file_client.download_file(
                timeout=self._config.operation_timeout_seconds
            )
            async for chunk in download.chunks():
                yield chunk
        except ResourceNotFoundError as exc:
            raise DocumentNotFoundError("source object was not found") from exc

    async def revoke_upload(self, upload_id: UUID) -> None:
        return None

    async def delete(self, object_key: str) -> None:
        try:
            await self._files.get_file_client(object_key).delete_file(
                timeout=self._config.operation_timeout_seconds
            )
        except ResourceNotFoundError:
            return

    async def promote(self, session: UploadSession) -> str:
        if session.object_key.startswith("governed/"):
            return session.object_key
        target = self.governed_key(session)
        await self._ensure_parent_directories(target)
        source = self._files.get_file_client(session.object_key)
        try:
            await source.rename_file(
                f"{self._config.source_file_system}/{target}",
                timeout=self._config.operation_timeout_seconds,
            )
        except ResourceNotFoundError as exc:
            try:
                await self._files.get_file_client(target).get_file_properties(
                    timeout=self._config.operation_timeout_seconds
                )
            except ResourceNotFoundError:
                raise DocumentNotFoundError("source object was not found during promotion") from exc
        return target

    async def _ensure_parent_directories(self, target: str) -> None:
        parts = target.rsplit("/", 1)[0].split("/")
        for index in range(1, len(parts) + 1):
            directory = "/".join(parts[:index])
            try:
                await self._files.create_directory(
                    directory,
                    timeout=self._config.operation_timeout_seconds,
                )
            except ResourceExistsError:
                continue

    @staticmethod
    def governed_key(session: UploadSession) -> str:
        collection = hashlib.sha256(session.collection_id.encode("utf-8")).hexdigest()[:16]
        return f"governed/{collection}/{session.document_id.hex}/{session.version_id.hex}/source"

    async def close(self) -> None:
        await self._service.close()


class AzureDataLakeArtifactStore:
    """Persist canonical DocumentEnvelope records in the private derived filesystem."""

    def __init__(
        self,
        *,
        config: AzureDataLakeConfig,
        service_client: DataLakeServiceClient,
    ) -> None:
        self._config = config
        self._service = service_client
        self._files = service_client.get_file_system_client(config.derived_file_system)

    @classmethod
    def from_identity(
        cls,
        *,
        config: AzureDataLakeConfig,
        identity: WorkloadIdentity,
    ) -> AzureDataLakeArtifactStore:
        credential = WorkloadIdentityTokenCredential(identity)
        service = DataLakeServiceClient(account_url=config.account_url, credential=credential)
        return cls(config=config, service_client=service)

    async def put(self, envelope: DocumentEnvelope) -> str:
        path = self._path(envelope.document_id, envelope.version_id)
        payload = envelope.model_dump_json().encode("utf-8")
        await self._files.get_file_client(path).upload_data(
            payload,
            length=len(payload),
            overwrite=True,
            metadata={
                "fdai_document_id": envelope.document_id.hex,
                "fdai_version_id": envelope.version_id.hex,
                "fdai_source_sha256": envelope.source_sha256,
            },
            timeout=self._config.operation_timeout_seconds,
        )
        return f"{self._config.account_url}/{self._config.derived_file_system}/{path}"

    async def delete(self, document_id: UUID, version_id: UUID) -> None:
        try:
            await self._files.get_file_client(self._path(document_id, version_id)).delete_file(
                timeout=self._config.operation_timeout_seconds
            )
        except ResourceNotFoundError:
            return

    async def close(self) -> None:
        await self._service.close()

    @staticmethod
    def _path(document_id: UUID, version_id: UUID) -> str:
        return f"documents/{document_id.hex}/versions/{version_id.hex}/envelope.json"


__all__ = [
    "AzureDataLakeArtifactStore",
    "AzureDataLakeConfig",
    "AzureDataLakeObjectStore",
    "WorkloadIdentityTokenCredential",
]
