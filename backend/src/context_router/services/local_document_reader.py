from __future__ import annotations

import re
from pathlib import Path

from context_router.config import settings
from context_router.db.models import Document, Project


class LocalDocumentReadError(Exception):
    """Base error for local document reads."""


class LocalDocumentNotFoundError(LocalDocumentReadError):
    """Raised when the indexed local document path no longer exists."""


class LocalDocumentAccessError(LocalDocumentReadError):
    """Raised when an indexed document path points outside its project root."""


FRONT_MATTER_PATTERN = re.compile(r"\A---\s*\n(?P<meta>.*?)\n---\s*\n?", re.DOTALL)


def read_document_content(document: Document) -> str:
    source_path = resolve_document_source_path(document)
    if source_path is None:
        return document.content_markdown

    try:
        raw_content = source_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise LocalDocumentNotFoundError(
            f"Local document file not found: {document.source_path}"
        ) from exc

    return strip_front_matter(raw_content)


def resolve_document_source_path(document: Document) -> Path | None:
    project = document.project
    roots = _project_root_candidates(project)
    if not roots:
        return None
    readable_roots = [root for root in roots if root.exists()]
    if not readable_roots:
        return None

    source = Path(document.source_path).expanduser()
    candidates = _source_path_candidates(source=source, roots=readable_roots)
    root_scoped_candidates = [
        candidate for candidate in candidates if _is_inside_any_root(candidate, readable_roots)
    ]
    if not root_scoped_candidates:
        raise LocalDocumentAccessError(
            f"Local document path is outside project root: {document.source_path}"
        )

    for candidate in root_scoped_candidates:
        if candidate.exists():
            return candidate

    return root_scoped_candidates[0]


def strip_front_matter(content: str) -> str:
    match = FRONT_MATTER_PATTERN.match(content)
    if match is None:
        return content
    return content[match.end() :].lstrip()


def _source_path_candidates(*, source: Path, roots: list[Path]) -> list[Path]:
    if source.is_absolute():
        mapped_source = _to_container_path(source)
        return _dedupe_paths([mapped_source, source])

    return _dedupe_paths([root / source for root in roots])


def _project_root_candidates(project: Project) -> list[Path]:
    if not project.root_path:
        return []

    host_root = Path(project.root_path).expanduser()
    mapped_root = _to_container_path(host_root)
    return _dedupe_paths([mapped_root, host_root])


def _to_container_path(path: Path) -> Path:
    host_root = settings.workspace_host_root
    container_root = settings.workspace_container_root
    if not host_root or not container_root:
        return path

    try:
        relative = path.resolve(strict=False).relative_to(
            Path(host_root).expanduser().resolve(strict=False)
        )
    except ValueError:
        return path
    return Path(container_root).expanduser() / relative


def _is_inside_any_root(path: Path, roots: list[Path]) -> bool:
    return any(_is_relative_to(path, root) for root in roots)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique_paths: list[Path] = []
    for path in paths:
        normalized = str(path.expanduser())
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(path.expanduser())
    return unique_paths
