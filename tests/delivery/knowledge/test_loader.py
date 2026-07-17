"""Tests for the Knowledge Base file loaders."""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.core.sandbox import (
    DocumentConverterSandboxCatalog,
    DocumentConverterSandboxProfile,
    SandboxPolicyError,
)
from fdai.delivery.knowledge.loader import (
    DEFAULT_CONVERTIBLE_SUFFIXES,
    DEFAULT_MAX_BYTES,
    documents_from_files,
    load_knowledge_documents,
    load_knowledge_documents_with_converter,
)
from fdai.shared.providers.document_converter import (
    DocumentConversionRequest,
    DocumentConversionResult,
)


def test_missing_root_yields_empty(tmp_path: Path) -> None:
    assert load_knowledge_documents(tmp_path / "nope") == []


def test_loads_text_and_plan_files_sorted(tmp_path: Path) -> None:
    (tmp_path / "runbook.md").write_text("# Runbook\nrestart the pod", encoding="utf-8")
    (tmp_path / "plan.tf").write_text('resource "azurerm_storage_account" "a" {}', encoding="utf-8")
    (tmp_path / "notes.bin").write_bytes(b"\x00\x01\x02")  # unknown suffix -> skipped

    docs = load_knowledge_documents(tmp_path)
    ids = [d.doc_id for d in docs]
    assert ids == ["plan.tf", "runbook.md"]  # sorted, .bin skipped
    plan = next(d for d in docs if d.doc_id == "plan.tf")
    assert plan.source_ref == "plan.tf"
    assert plan.metadata["suffix"] == ".tf"


def test_nested_paths_use_relative_posix_id(tmp_path: Path) -> None:
    nested = tmp_path / "docs" / "arch"
    nested.mkdir(parents=True)
    (nested / "overview.md").write_text("architecture overview", encoding="utf-8")
    docs = load_knowledge_documents(tmp_path)
    assert [d.doc_id for d in docs] == ["docs/arch/overview.md"]


def test_oversized_file_skipped(tmp_path: Path) -> None:
    (tmp_path / "big.md").write_text("x" * 100, encoding="utf-8")
    docs = load_knowledge_documents(tmp_path, max_bytes=10)
    assert docs == []


def test_binary_utf8_file_skipped(tmp_path: Path) -> None:
    # A .md file with invalid UTF-8 is skipped, not crashed on.
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe\x00bad")
    docs = load_knowledge_documents(tmp_path)
    assert docs == []


def test_blank_file_skipped(tmp_path: Path) -> None:
    (tmp_path / "empty.md").write_text("   \n\t", encoding="utf-8")
    assert load_knowledge_documents(tmp_path) == []


def test_invalid_max_bytes_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_knowledge_documents(tmp_path, max_bytes=0)


def test_documents_from_files_relative_to_root(tmp_path: Path) -> None:
    f = tmp_path / "sub" / "r.md"
    f.parent.mkdir()
    f.write_text("body", encoding="utf-8")
    docs = documents_from_files([f], root=tmp_path)
    assert len(docs) == 1
    assert docs[0].doc_id == "sub/r.md"


def test_documents_from_files_outside_root_skipped(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    f = other / "x.md"
    f.write_text("body", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    assert documents_from_files([f], root=root) == []


def test_default_max_bytes_is_16mb() -> None:
    assert DEFAULT_MAX_BYTES == 16 * 1024 * 1024


class _Converter:
    def __init__(self) -> None:
        self.requests: list[DocumentConversionRequest] = []

    async def convert(
        self,
        request: DocumentConversionRequest,
    ) -> DocumentConversionResult:
        self.requests.append(request)
        return DocumentConversionResult(text="converted runbook")


def _converter_catalog() -> DocumentConverterSandboxCatalog:
    return DocumentConverterSandboxCatalog(
        (
            DocumentConverterSandboxProfile(
                profile_id="document.office",
                converter_ids=frozenset({"office.text"}),
                allowed_suffixes=DEFAULT_CONVERTIBLE_SUFFIXES,
                max_input_bytes=1_000,
                max_output_bytes=1_000,
            ),
        )
    )


async def test_binary_documents_require_profiled_conversion(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("plain text", encoding="utf-8")
    (tmp_path / "runbook.pdf").write_bytes(b"pdf-content")
    converter = _Converter()

    documents = await load_knowledge_documents_with_converter(
        tmp_path,
        converter_id="office.text",
        converter=converter,
        sandbox_catalog=_converter_catalog(),
    )

    assert [document.doc_id for document in documents] == ["notes.md", "runbook.pdf"]
    assert documents[1].text == "converted runbook"
    assert documents[1].metadata["converter_id"] == "office.text"
    assert converter.requests[0].source_ref == "runbook.pdf"


async def test_unprofiled_binary_converter_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "runbook.pdf").write_bytes(b"pdf-content")

    with pytest.raises(SandboxPolicyError, match="no sandbox profile"):
        await load_knowledge_documents_with_converter(
            tmp_path,
            converter_id="office.text",
            converter=_Converter(),
            sandbox_catalog=DocumentConverterSandboxCatalog(),
        )
