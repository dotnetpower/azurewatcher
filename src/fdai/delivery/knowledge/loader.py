"""File-system loader for Knowledge Base ingestion.

Turns local files (a console upload landing in a drop directory, a repo of
runbooks, a committed **resource plan**) into
:class:`~fdai.shared.providers.knowledge.KnowledgeDocument` records ready to
hand to :meth:`KnowledgeSource.ingest` /
:meth:`~fdai.core.knowledge.registry.KnowledgeRegistry.register`.

This is the delivery-side counterpart of
:class:`~fdai.shared.providers.manual_source.DropDirectoryManualSource`
(which feeds the rule distiller): one generic file adapter covers every
credential-free ingestion mode - an operator drop, a console upload, an
email-in gateway - because they all land a file on disk.

Scope and boundaries
--------------------

- **Text formats by default.** Plain-text sources (``.md``, ``.txt``,
  ``.rst``) and infrastructure/plan text (``.tf``, ``.tfvars``, ``.json``,
  ``.yaml``, ``.yml``, ``.rego``) are read directly. Binary office formats
  (``.pdf`` / ``.docx`` / ``.pptx``) are accepted only through an explicitly
  injected converter and server-owned sandbox profile. The upstream package
  supplies no concrete converter. Unknown extensions are skipped, never guessed.
- **Fail-safe.** An oversized file, an undecodable (binary) file, or an
  unreadable path is skipped with a warning; one bad file never aborts a
  batch. The caller ingests whatever loaded cleanly.
- **Secret-safe / customer-agnostic.** ``doc_id`` and ``source_ref`` are the
  path **relative to the root**, so an absolute host path never leaks into a
  citation or audit entry. The file body is the document text; the caller is
  responsible for not dropping secret-bearing files into the root.
- **Deterministic.** Files are visited in sorted order and ``doc_id`` is the
  stable relative POSIX path, so re-loading the same tree upserts in place
  (the ``KnowledgeSource`` keys chunks on ``doc_id``).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from fdai.core.sandbox import (
    DocumentConverterSandboxCatalog,
    ProfiledDocumentConverter,
    SandboxPolicyError,
)
from fdai.shared.providers.document_converter import (
    DocumentConversionRequest,
    DocumentConverter,
)
from fdai.shared.providers.knowledge import KnowledgeDocument

_LOGGER = logging.getLogger("fdai.delivery.knowledge.loader")

#: Text extensions read directly without a converter.
DEFAULT_TEXT_SUFFIXES: frozenset[str] = frozenset(
    {
        ".md",
        ".txt",
        ".rst",
        ".tf",
        ".tfvars",
        ".json",
        ".yaml",
        ".yml",
        ".rego",
    }
)

DEFAULT_CONVERTIBLE_SUFFIXES: frozenset[str] = frozenset({".pdf", ".docx", ".pptx"})

#: SRE-agent parity: a 16 MB per-file ceiling. A larger file is skipped.
DEFAULT_MAX_BYTES: int = 16 * 1024 * 1024


def load_knowledge_documents(
    root: Path | str,
    *,
    suffixes: frozenset[str] = DEFAULT_TEXT_SUFFIXES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> list[KnowledgeDocument]:
    """Load every supported text file under ``root`` into documents.

    Recurses ``root`` in sorted order, reads each file whose suffix is in
    ``suffixes`` and whose size is at most ``max_bytes``, and builds a
    :class:`KnowledgeDocument` whose ``doc_id`` / ``source_ref`` is the path
    relative to ``root``. A single file that is oversized, binary
    (undecodable UTF-8), or unreadable is skipped with a warning rather than
    raising, so a batch never fails on one bad file.

    A ``root`` that does not exist or is not a directory yields ``[]`` - an
    unconfigured drop directory is "nothing to ingest", not an error.
    """
    if max_bytes < 1:
        raise ValueError("max_bytes MUST be >= 1")

    root_path = Path(root)
    if not root_path.is_dir():
        _LOGGER.info("knowledge root %s is not a directory; nothing to load", root_path)
        return []

    documents: list[KnowledgeDocument] = []
    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in suffixes:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            _LOGGER.warning("cannot stat %s; skipping", path, exc_info=True)
            continue
        if size > max_bytes:
            _LOGGER.warning("skipping %s: %d bytes exceeds max_bytes=%d", path, size, max_bytes)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            _LOGGER.warning("cannot read %s as UTF-8 text; skipping", path, exc_info=True)
            continue
        if not text.strip():
            continue
        rel = path.relative_to(root_path).as_posix()
        documents.append(
            KnowledgeDocument(
                doc_id=rel,
                text=text,
                source_ref=rel,
                metadata={"suffix": path.suffix.lower(), "bytes": str(size)},
            )
        )
    return documents


def documents_from_files(
    paths: Sequence[Path | str],
    *,
    root: Path | str,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> list[KnowledgeDocument]:
    """Load an explicit list of files (e.g. a single console upload).

    Like :func:`load_knowledge_documents` but for a caller-supplied file
    list rather than a directory walk. ``root`` anchors the relative
    ``doc_id`` / ``source_ref`` so uploads keep stable, host-path-free ids.
    A path outside ``root``, oversized, binary, or unreadable is skipped.
    """
    if max_bytes < 1:
        raise ValueError("max_bytes MUST be >= 1")

    root_path = Path(root)
    documents: list[KnowledgeDocument] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            _LOGGER.warning("not a file: %s; skipping", path)
            continue
        try:
            rel = path.resolve().relative_to(root_path.resolve()).as_posix()
        except ValueError:
            _LOGGER.warning("%s is outside root %s; skipping", path, root_path)
            continue
        try:
            size = path.stat().st_size
        except OSError:
            _LOGGER.warning("cannot stat %s; skipping", path, exc_info=True)
            continue
        if size > max_bytes:
            _LOGGER.warning("skipping %s: %d bytes exceeds max_bytes=%d", path, size, max_bytes)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            _LOGGER.warning("cannot read %s as UTF-8 text; skipping", path, exc_info=True)
            continue
        if not text.strip():
            continue
        documents.append(
            KnowledgeDocument(
                doc_id=rel,
                text=text,
                source_ref=rel,
                metadata={"suffix": path.suffix.lower(), "bytes": str(size)},
            )
        )
    return documents


async def load_knowledge_documents_with_converter(
    root: Path | str,
    *,
    converter_id: str,
    converter: DocumentConverter,
    sandbox_catalog: DocumentConverterSandboxCatalog,
    convertible_suffixes: frozenset[str] = DEFAULT_CONVERTIBLE_SUFFIXES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_output_bytes: int = 5_000_000,
) -> list[KnowledgeDocument]:
    """Load text plus explicitly sandboxed binary document conversions."""
    if max_bytes < 1 or max_output_bytes < 1:
        raise ValueError("document conversion byte limits MUST be positive")
    if not convertible_suffixes.isdisjoint(DEFAULT_TEXT_SUFFIXES):
        raise ValueError("convertible suffixes MUST NOT overlap direct text suffixes")

    root_path = Path(root)
    documents = load_knowledge_documents(root_path, max_bytes=max_bytes)
    if not root_path.is_dir():
        return documents

    profiled = ProfiledDocumentConverter(
        catalog=sandbox_catalog,
        converter=converter,
    )
    for path in sorted(root_path.rglob("*")):
        suffix = path.suffix.lower()
        if not path.is_file() or suffix not in convertible_suffixes:
            continue
        try:
            size = path.stat().st_size
            if size > max_bytes:
                _LOGGER.warning(
                    "skipping %s: %d bytes exceeds max_bytes=%d",
                    path,
                    size,
                    max_bytes,
                )
                continue
            content = path.read_bytes()
            if not content:
                continue
            source_ref = path.relative_to(root_path).as_posix()
            result = await profiled.convert(
                DocumentConversionRequest(
                    converter_id=converter_id,
                    source_ref=source_ref,
                    source_suffix=suffix,
                    content=content,
                    max_output_bytes=max_output_bytes,
                )
            )
        except SandboxPolicyError:
            raise
        except (OSError, ValueError):
            _LOGGER.warning("cannot convert %s; skipping", path, exc_info=True)
            continue
        documents.append(
            KnowledgeDocument(
                doc_id=source_ref,
                text=result.text,
                source_ref=source_ref,
                metadata={
                    "suffix": suffix,
                    "bytes": str(size),
                    "converter_id": converter_id,
                },
            )
        )
    documents.sort(key=lambda document: document.doc_id)
    return documents


__all__ = [
    "DEFAULT_CONVERTIBLE_SUFFIXES",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_TEXT_SUFFIXES",
    "documents_from_files",
    "load_knowledge_documents",
    "load_knowledge_documents_with_converter",
]
