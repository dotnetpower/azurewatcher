"""Tests for the explicit local document-ingestion gateway composition."""

from __future__ import annotations

import asyncio
import hashlib

import pytest
from starlette.testclient import TestClient

from fdai.delivery.ingestion_gateway import dev


def test_dev_gateway_requires_explicit_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FDAI_INGESTION_GATEWAY_DEV_MODE", raising=False)

    with pytest.raises(ValueError, match="FDAI_INGESTION_GATEWAY_DEV_MODE"):
        dev.app()


def test_dev_gateway_serves_direct_upload_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_INGESTION_GATEWAY_DEV_MODE", "1")
    client = TestClient(dev.app())

    response = client.get(
        "/ingestion/capabilities",
        headers={"origin": "http://127.0.0.1:5190"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5190"
    payload = response.json()
    assert payload["direct_upload"] is True
    assert payload["max_batch_count"] == 10
    assert "text" in payload["supported_formats"]


def test_dev_gateway_accepts_explicit_cors_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_INGESTION_GATEWAY_DEV_MODE", "1")
    monkeypatch.setenv(
        "FDAI_INGESTION_GATEWAY_CORS_ALLOW_ORIGINS",
        "http://127.0.0.1:5191, https://console.example.com/",
    )
    client = TestClient(dev.app())

    response = client.get(
        "/ingestion/capabilities",
        headers={"origin": "https://console.example.com"},
    )

    assert response.headers["access-control-allow-origin"] == "https://console.example.com"


def test_dev_gateway_rejects_unsafe_cors_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_INGESTION_GATEWAY_DEV_MODE", "1")
    monkeypatch.setenv("FDAI_INGESTION_GATEWAY_CORS_ALLOW_ORIGINS", "*")

    with pytest.raises(ValueError, match="explicit HTTP\\(S\\) origins"):
        dev.app()


def test_dev_gateway_builds_grounded_handover_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_INGESTION_GATEWAY_DEV_MODE", "1")
    client = TestClient(dev.app())
    content = b"Monitoring owner: Jordan Lee is accountable for anomaly watching"
    body = {
        "source_name": "raci.txt",
        "collection_id": "shared-knowledge",
        "media_type_hint": "text/plain",
        "expected_size": len(content),
        "expected_sha256": hashlib.sha256(content).hexdigest(),
        "storage_mode": "managed_copy",
        "purposes": ["handover_bootstrap"],
        "access_descriptor_ref": "collection:shared-knowledge",
        "retention_policy_version": "local-policy-v1",
    }

    created = client.post("/ingestion/uploads", json=body)
    assert created.status_code == 201
    upload_id = created.json()["session"]["upload_id"]
    assert client.put(f"/ingestion/uploads/{upload_id}/content", content=content).status_code == 204
    assert client.post(f"/ingestion/uploads/{upload_id}/complete").status_code == 202

    result = client.get(f"/ingestion/uploads/{upload_id}/handover-draft")

    assert result.status_code == 200
    payload = result.json()
    assert payload["draft"]["outcome"] == "drafted"
    assert payload["draft"]["mappings"][0]["agent_name"] == "Heimdall"
    assert payload["draft"]["mappings"][0]["citations"][0]["line"] == 1
    assert "stewardship:" in payload["yaml"]


def test_dev_gateway_chunks_embeds_and_indexes_uploaded_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_INGESTION_GATEWAY_DEV_MODE", "1")
    application = dev.app()
    client = TestClient(application)
    content = b"Disk recovery steps\nClear old logs when the disk is full"
    body = {
        "source_name": "disk-runbook.txt",
        "collection_id": "shared-knowledge",
        "media_type_hint": "text/plain",
        "expected_size": len(content),
        "expected_sha256": hashlib.sha256(content).hexdigest(),
        "storage_mode": "managed_copy",
        "purposes": ["knowledge_base"],
        "access_descriptor_ref": "collection:shared-knowledge",
        "retention_policy_version": "local-policy-v1",
    }

    created = client.post("/ingestion/uploads", json=body)
    upload_id = created.json()["session"]["upload_id"]
    assert client.put(f"/ingestion/uploads/{upload_id}/content", content=content).status_code == 204
    assert client.post(f"/ingestion/uploads/{upload_id}/complete").status_code == 202

    hits = asyncio.run(
        application.state.document_index.search(
            "disk full",
            collection_id="shared-knowledge",
            allowed_access_refs=frozenset({"collection:shared-knowledge"}),
            k=2,
        )
    )

    assert len(hits) == 2
    assert {hit.metadata["locator"] for hit in hits} == {"line:1", "line:2"}
    assert all(hit.source_ref.startswith("document://") for hit in hits)

    response = client.get(
        "/documents/search",
        params={"q": "disk full", "collection_id": "shared-knowledge", "limit": 2},
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
    assert {item["locator"] for item in response.json()["items"]} == {"line:1", "line:2"}
