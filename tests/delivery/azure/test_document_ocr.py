from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from fdai.delivery.azure.document_ocr import (
    AzureDocumentIntelligenceOcr,
    AzureDocumentOcrConfig,
    AzureDocumentOcrError,
)
from fdai.shared.contracts import (
    AccessDescriptor,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    ProtectionState,
    RetentionPolicy,
)
from fdai.shared.providers.workload_identity import IdentityToken


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(token="identity-token", audience=audience, expires_at=None)


def _version() -> DocumentVersion:
    now = datetime(2026, 7, 22, tzinfo=UTC)
    return DocumentVersion(
        document_id=UUID(int=1),
        version_id=UUID(int=2),
        upload_id=UUID(int=3),
        source_name="handover.png",
        source_sha256="0" * 64,
        size_bytes=4,
        media_type="image/png",
        observed_format="image",
        state=DocumentState.EXTRACTING,
        protection_state=ProtectionState.NONE,
        access=AccessDescriptor(reference="acl", collection_id="collection"),
        retention=RetentionPolicy(policy_version="v1"),
        purposes=(DocumentPurpose.HANDOVER_BOOTSTRAP,),
        uploader_id="operator",
        created_at=now,
        updated_at=now,
    )


async def test_ocr_returns_page_line_citations() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.headers["Authorization"] == "Bearer identity-token"
        if request.method == "POST":
            assert request.headers["Content-Type"] == "image/png"
            return httpx.Response(
                202,
                headers={
                    "operation-location": "https://ocr.example.com/documentintelligence/operations/1"
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "analyzeResult": {
                    "pages": [
                        {
                            "pageNumber": 1,
                            "lines": [
                                {"content": "Thor owner: Example Operator"},
                                {"content": "Heimdall informed: Platform Team"},
                            ],
                        }
                    ]
                },
            },
        )

    ocr = AzureDocumentIntelligenceOcr(
        config=AzureDocumentOcrConfig(endpoint="https://ocr.example.com"),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    units = await ocr.extract(version=_version(), content=b"data")

    assert calls == 2
    assert [unit.locator for unit in units] == ["page:1:line:1", "page:1:line:2"]
    assert units[0].text == "Thor owner: Example Operator"


async def test_ocr_rejects_operation_location_outside_configured_origin() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            headers={"operation-location": "https://example.com/operations/1"},
        )

    ocr = AzureDocumentIntelligenceOcr(
        config=AzureDocumentOcrConfig(endpoint="https://ocr.example.com"),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AzureDocumentOcrError, match="outside"):
        await ocr.extract(version=_version(), content=b"data")


async def test_ocr_rejects_output_over_line_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202,
                headers={
                    "operation-location": "https://ocr.example.com/documentintelligence/operations/1"
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "analyzeResult": {
                    "pages": [{"pageNumber": 1, "lines": [{"content": "a"}, {"content": "b"}]}]
                },
            },
        )

    ocr = AzureDocumentIntelligenceOcr(
        config=AzureDocumentOcrConfig(
            endpoint="https://ocr.example.com",
            max_lines=1,
        ),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AzureDocumentOcrError, match="bounds"):
        await ocr.extract(version=_version(), content=b"data")
