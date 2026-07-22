"""Durable idempotency ledger for development gateway mutations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Protocol
from urllib.parse import urlparse

import httpx

_STORAGE_AUDIENCE = "https://storage.azure.com/"
_STORAGE_API_VERSION = "2025-05-05"
_MAX_RECORD_BYTES = 262_144


class IdempotencyError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class TokenProvider(Protocol):
    async def get_token(self, audience: str) -> str: ...


class IdempotencyLedger(Protocol):
    async def begin(
        self, idempotency_key: str, request_digest: str
    ) -> Mapping[str, object] | None: ...

    async def complete(
        self,
        idempotency_key: str,
        request_digest: str,
        response: Mapping[str, object],
    ) -> None: ...

    async def abort(self, idempotency_key: str, request_digest: str) -> None: ...


@dataclass(frozen=True, slots=True)
class AzureBlobIdempotencyConfig:
    container_url: str

    def __post_init__(self) -> None:
        parsed = urlparse(self.container_url)
        path_segments = tuple(segment for segment in parsed.path.split("/") if segment)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or len(path_segments) != 1
        ):
            raise ValueError("idempotency container URL MUST identify one HTTPS container")


class AzureBlobIdempotencyLedger:
    """Use conditional Blob writes to serialize mutation delivery by key."""

    def __init__(
        self,
        *,
        config: AzureBlobIdempotencyConfig,
        token_provider: TokenProvider,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._container_url = config.container_url.rstrip("/")
        self._tokens = token_provider
        self._http = http_client
        self._claims: dict[str, str] = {}

    async def begin(self, idempotency_key: str, request_digest: str) -> Mapping[str, object] | None:
        blob_url = self._blob_url(idempotency_key)
        record = self._encode_record({"state": "pending", "request_digest": request_digest})
        headers = await self._headers()
        headers.update(
            {
                "Content-Type": "application/json",
                "If-None-Match": "*",
                "x-ms-blob-type": "BlockBlob",
            }
        )
        response = await self._request(
            "PUT",
            blob_url,
            headers=headers,
            content=record,
        )
        if response.status_code == 201:
            etag = response.headers.get("ETag", "")
            if not etag:
                raise IdempotencyError(
                    503,
                    "idempotency_unavailable",
                    "idempotency claim response did not include an ETag",
                )
            self._claims[idempotency_key] = etag
            return None
        if response.status_code not in {409, 412}:
            self._raise_storage_error(response)

        existing, _etag = await self._read(blob_url)
        if existing.get("request_digest") != request_digest:
            raise IdempotencyError(
                409,
                "idempotency_conflict",
                "idempotency key was already used for a different request",
            )
        if existing.get("state") == "completed":
            result = existing.get("response")
            if isinstance(result, Mapping):
                return dict(result)
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "completed idempotency record did not contain a response",
            )
        if existing.get("state") == "pending":
            raise IdempotencyError(
                409,
                "idempotency_in_progress",
                "an operation with this idempotency key is already in progress",
            )
        raise IdempotencyError(
            503,
            "idempotency_unavailable",
            "idempotency record state was invalid",
        )

    async def complete(
        self,
        idempotency_key: str,
        request_digest: str,
        response: Mapping[str, object],
    ) -> None:
        etag = self._claims.get(idempotency_key)
        if not etag:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "idempotency claim was not held by this invocation",
            )
        record = self._encode_record(
            {
                "state": "completed",
                "request_digest": request_digest,
                "response": response,
            }
        )
        headers = await self._headers()
        headers.update(
            {
                "Content-Type": "application/json",
                "If-Match": etag,
                "x-ms-blob-type": "BlockBlob",
            }
        )
        result = await self._request(
            "PUT",
            self._blob_url(idempotency_key),
            headers=headers,
            content=record,
        )
        if result.status_code != 201:
            self._raise_storage_error(result)
        self._claims.pop(idempotency_key, None)

    async def abort(self, idempotency_key: str, request_digest: str) -> None:
        del request_digest
        etag = self._claims.pop(idempotency_key, None)
        if not etag:
            return
        headers = await self._headers()
        headers["If-Match"] = etag
        response = await self._request(
            "DELETE",
            self._blob_url(idempotency_key),
            headers=headers,
        )
        if response.status_code not in {202, 404}:
            self._raise_storage_error(response)

    async def _read(self, blob_url: str) -> tuple[Mapping[str, object], str]:
        response = await self._request("GET", blob_url, headers=await self._headers())
        if response.status_code != 200:
            self._raise_storage_error(response)
        if len(response.content) > _MAX_RECORD_BYTES:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "idempotency record exceeded its size limit",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "idempotency record was not valid JSON",
            ) from exc
        etag = response.headers.get("ETag", "")
        if not isinstance(payload, Mapping) or not etag:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "idempotency record was incomplete",
            )
        return payload, etag

    async def _headers(self) -> dict[str, str]:
        token = await self._tokens.get_token(_STORAGE_AUDIENCE)
        return {
            "Authorization": f"Bearer {token}",
            "x-ms-date": format_datetime(datetime.now(UTC), usegmt=True),
            "x-ms-version": _STORAGE_API_VERSION,
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        content: bytes | None = None,
    ) -> httpx.Response:
        try:
            return await self._http.request(
                method,
                url,
                headers=headers,
                content=content,
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "idempotency storage request failed",
            ) from exc

    def _blob_url(self, idempotency_key: str) -> str:
        key_digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return f"{self._container_url}/{key_digest}.json"

    @staticmethod
    def _encode_record(record: Mapping[str, object]) -> bytes:
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > _MAX_RECORD_BYTES:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "idempotency record exceeded its size limit",
            )
        return encoded

    @staticmethod
    def _raise_storage_error(response: httpx.Response) -> None:
        raise IdempotencyError(
            503,
            "idempotency_unavailable",
            f"idempotency storage returned HTTP {response.status_code}",
        )


__all__ = [
    "AzureBlobIdempotencyConfig",
    "AzureBlobIdempotencyLedger",
    "IdempotencyError",
    "IdempotencyLedger",
]
