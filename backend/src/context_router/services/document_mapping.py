from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from context_router.config import settings
from context_router.db.models import Project


class DocumentMappingError(ValueError):
    pass


class DocumentMappingConflictError(DocumentMappingError):
    pass


@dataclass(frozen=True)
class DocumentMappingCandidate:
    docs_path: str
    markdown_count: int
    mapped_project_slug: str | None


def documents_root() -> Path:
    configured_root = Path(settings.documents_container_root).expanduser()
    try:
        resolved_root = configured_root.resolve(strict=True)
    except FileNotFoundError as exc:
        raise DocumentMappingError(f"Documents root not found: {configured_root}") from exc
    if not resolved_root.is_dir():
        raise DocumentMappingError(f"Documents root is not a directory: {configured_root}")
    return resolved_root


def resolve_document_root(project: Project) -> Path:
    if not project.docs_path:
        raise DocumentMappingError(f"Project has no document mapping: {project.slug}")
    return _resolve_docs_path(project.docs_path)


def list_document_candidates(session: Session) -> list[DocumentMappingCandidate]:
    root = documents_root()
    occupied = {
        docs_path: project_slug
        for docs_path, project_slug in session.execute(
            select(Project.docs_path, Project.slug).where(Project.docs_path.is_not(None))
        ).all()
        if docs_path
    }
    candidates: list[DocumentMappingCandidate] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.is_symlink():
            continue
        try:
            resolved = _resolve_docs_path(child.name)
        except DocumentMappingError:
            continue
        markdown_count = 1 + sum(
            1
            for path in (resolved / "docs").rglob("*.md")
            if path.is_file() and not path.is_symlink()
        )
        candidates.append(
            DocumentMappingCandidate(
                docs_path=child.name,
                markdown_count=markdown_count,
                mapped_project_slug=occupied.get(child.name),
            )
        )
    return candidates


def assign_document_mapping(
    session: Session,
    *,
    project: Project,
    docs_path: str,
) -> Project:
    resolved = _resolve_docs_path(docs_path)
    normalized = resolved.relative_to(documents_root()).as_posix()
    occupied = session.scalar(
        select(Project).where(
            Project.docs_path == normalized,
            Project.id != project.id,
        )
    )
    if occupied is not None:
        raise DocumentMappingConflictError(
            f"Document directory {normalized} is already mapped to {occupied.slug}"
        )

    project.docs_path = normalized
    project.last_synced_at = None
    project.last_sync_status = "never"
    project.last_sync_summary = {}
    return project


def _resolve_docs_path(docs_path: str) -> Path:
    relative = Path(docs_path.strip())
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise DocumentMappingError(
            f"Document mapping must be a direct relative directory: {docs_path}"
        )

    root = documents_root()
    candidate = root / relative
    if candidate.is_symlink():
        raise DocumentMappingError(f"Mapped document directory cannot be a symlink: {docs_path}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise DocumentMappingError(
            f"Mapped document directory is unavailable: {docs_path}"
        ) from exc

    agents_path = resolved / "AGENTS.md"
    docs_directory = resolved / "docs"
    if (
        not agents_path.is_file()
        or agents_path.is_symlink()
        or not docs_directory.is_dir()
        or docs_directory.is_symlink()
    ):
        raise DocumentMappingError(
            f"Mapped directory requires regular AGENTS.md and docs/: {docs_path}"
        )
    return resolved
