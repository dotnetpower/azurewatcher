"""Offline tests for the governed pgvector document index."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from uuid import UUID, uuid4

import psycopg
import pytest

from fdai.delivery.document_index import document_version_ref
from fdai.delivery.pgvector.document_index import (
    PgvectorDocumentIndex,
    PgvectorDocumentIndexConfig,
)
from fdai.shared.contracts import (
    DocumentEnvelope,
    DocumentPurpose,
    ProtectionState,
    StructuralUnit,
)
from fdai.shared.providers.document_ingestion import DocumentIndex
from fdai.shared.providers.secret_provider import SecretProvider

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000201")
_VERSION_ID = UUID("00000000-0000-0000-0000-000000000202")
_REPO_ROOT = Path(__file__).resolve().parents[3]


class _Embedder:
    async def embed(self, text: str) -> Sequence[float]:
        vector = [0.0] * 384
        vector[len(text) % len(vector)] = 1.0
        return vector


class _Secrets(SecretProvider):
    def __init__(self, dsn: str = "postgresql://placeholder") -> None:
        self._dsn = dsn

    async def get(self, name: str) -> str:
        assert name == "postgres/dsn"
        return self._dsn


class _Transaction(AbstractAsyncContextManager[None]):
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._rows = rows or []

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(self, sql: str, params: Any = None) -> _Cursor:
        self.calls.append((sql, params))
        return _Cursor(self._rows if "SELECT doc_id" in sql else [])

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False


def _envelope() -> DocumentEnvelope:
    return DocumentEnvelope(
        document_id=_DOCUMENT_ID,
        version_id=_VERSION_ID,
        source_sha256="b" * 64,
        media_type="text/plain",
        observed_format="text",
        size_bytes=10,
        collection_id="shared-knowledge",
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        protection_state=ProtectionState.NONE,
        access_descriptor_ref="collection:shared-knowledge",
        units=(
            StructuralUnit(unit_id="line-1", kind="text", locator="line:1", text="alpha"),
            StructuralUnit(unit_id="line-2", kind="text", locator="line:2", text="beta"),
        ),
        extractor_name="test",
        extractor_version="1.0.0",
    )


def _index(*, dsn: str = "postgresql://placeholder") -> PgvectorDocumentIndex:
    return PgvectorDocumentIndex(
        config=PgvectorDocumentIndexConfig(dsn_secret="postgres/dsn"),
        embedder=_Embedder(),
        secrets=_Secrets(dsn),
    )


def test_pgvector_document_index_satisfies_protocol() -> None:
    assert isinstance(_index(), DocumentIndex)


def test_config_rejects_unsafe_values() -> None:
    with pytest.raises(ValueError, match="SQL identifier"):
        PgvectorDocumentIndexConfig(dsn_secret="postgres/dsn", table="chunk; DROP")
    with pytest.raises(ValueError, match="overlap"):
        PgvectorDocumentIndexConfig(dsn_secret="postgres/dsn", max_chars=100, overlap=100)


async def test_commit_atomically_replaces_version_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _Connection()

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)

    assert await _index().commit(_envelope()) == 2

    mutation_calls = [call for call in connection.calls if "knowledge_chunk" in call[0]]
    assert "DELETE FROM knowledge_chunk" in mutation_calls[0][0]
    assert len([call for call in mutation_calls if "INSERT INTO" in call[0]]) == 2
    first_metadata = json.loads(mutation_calls[1][1][-1])
    assert first_metadata["governed_document"] == "true"
    assert first_metadata["locator"] == "line:1"
    assert first_metadata["access_descriptor_ref"] == "collection:shared-knowledge"


async def test_delete_targets_one_document_version(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _Connection()

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)

    await _index().delete(_DOCUMENT_ID, _VERSION_ID)

    delete_call = next(call for call in connection.calls if "DELETE FROM" in call[0])
    assert delete_call[1] == (document_version_ref(_DOCUMENT_ID, _VERSION_ID),)


async def test_search_applies_collection_and_access_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "doc_id": f"{_DOCUMENT_ID}:{_VERSION_ID}",
            "chunk_id": "chunk-1",
            "text": "alpha",
            "source_ref": "document://example#unit",
            "metadata": {"locator": "line:1"},
            "score": 0.75,
        }
    ]
    connection = _Connection(rows)

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)

    hits = await _index().search(
        "alpha",
        collection_id="shared-knowledge",
        allowed_access_refs=frozenset({"collection:shared-knowledge"}),
    )

    select_call = next(call for call in connection.calls if "SELECT doc_id" in call[0])
    assert "metadata->>'governed_document' = 'true'" in select_call[0]
    assert "metadata->>'collection_id'" in select_call[0]
    assert "metadata->>'access_descriptor_ref' = ANY" in select_call[0]
    assert select_call[1][1:3] == (
        "shared-knowledge",
        ["collection:shared-knowledge"],
    )
    assert hits[0].metadata["locator"] == "line:1"


@pytest.mark.integration
async def test_live_pgvector_commit_search_and_delete() -> None:
    database_url = os.environ.get("FDAI_DATABASE_URL")
    if not database_url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    upgrade = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert upgrade.returncode == 0, upgrade.stderr
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    collection_id = f"document-index-test-{uuid4().hex}"
    access_ref = f"collection:{collection_id}"
    envelope = _envelope().model_copy(
        update={
            "document_id": uuid4(),
            "version_id": uuid4(),
            "collection_id": collection_id,
            "access_descriptor_ref": access_ref,
        }
    )
    index = _index(dsn=dsn)

    try:
        assert await index.commit(envelope) == 2
        denied = await index.search(
            "alpha",
            collection_id=collection_id,
            allowed_access_refs=frozenset({"collection:other"}),
        )
        hits = await index.search(
            "alpha",
            collection_id=collection_id,
            allowed_access_refs=frozenset({access_ref}),
        )

        assert denied == ()
        assert len(hits) == 2
        assert {hit.metadata["locator"] for hit in hits} == {"line:1", "line:2"}
    finally:
        await index.delete(envelope.document_id, envelope.version_id)

    assert (
        await index.search(
            "alpha",
            collection_id=collection_id,
            allowed_access_refs=frozenset({access_ref}),
        )
        == ()
    )
