from __future__ import annotations

import re
from pathlib import Path

from context_router.db.models import Document
from context_router.services.document_mapping import (
    DocumentMappingError,
    resolve_document_storage_root,
)


class LocalDocumentReadError(Exception):
    """Base error for mapped document reads."""


class LocalDocumentNotFoundError(LocalDocumentReadError):
    """Raised when the indexed mapped document no longer exists."""


class LocalDocumentAccessError(LocalDocumentReadError):
    """Raised when an indexed path is not a safe mapped document path."""


FRONT_MATTER_PATTERN = re.compile(r"\A---\s*\n(?P<meta>.*?)\n---\s*\n?", re.DOTALL)


def read_document_content(document: Document) -> str:
    source_path = resolve_document_source_path(document)
    try:
        raw_content = source_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise LocalDocumentNotFoundError(
            f"Mapped document file not found: {document.source_path}; sync documents again"
        ) from exc
    except (IsADirectoryError, OSError) as exc:
        raise LocalDocumentAccessError(
            f"Mapped document file is not readable: {document.source_path}"
        ) from exc
    return strip_front_matter(raw_content)


def resolve_document_source_path(document: Document) -> Path:
    try:
        document_root = resolve_document_storage_root(document.project)
    except DocumentMappingError as exc:
        raise LocalDocumentAccessError(str(exc)) from exc

    source = Path(document.source_path)
    if source.is_absolute() or ".." in source.parts:
        raise LocalDocumentAccessError(
            f"Mapped document source path is invalid: {document.source_path}"
        )
    if source != Path("AGENTS.md") and (not source.parts or source.parts[0] != "docs"):
        raise LocalDocumentAccessError(
            f"Mapped document source is outside AGENTS.md and docs/: {document.source_path}"
        )

    candidate = document_root / source
    current = document_root
    for part in source.parts:
        current = current / part
        if current.is_symlink():
            raise LocalDocumentAccessError(
                f"Mapped document source cannot be a symlink: {document.source_path}"
            )

    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(document_root)
    except ValueError as exc:
        raise LocalDocumentAccessError(
            f"Mapped document source escapes document root: {document.source_path}"
        ) from exc
    return resolved


def strip_front_matter(content: str) -> str:
    match = FRONT_MATTER_PATTERN.match(content)
    if match is None:
        return content
    return content[match.end() :].lstrip()
