from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from context_router.config import settings
from context_router.db.models import Document, DocumentLink, Project, RetrievalHit
from context_router.schemas.documents import DocumentCreate
from context_router.services.document_store import upsert_document


@dataclass(frozen=True)
class MarkdownDocument:
    doc_id: str
    title: str
    source_path: Path
    display_source_path: Path
    doc_type: str
    area: str | None
    tags: list[str]
    content_markdown: str


@dataclass(frozen=True)
class MarkdownLink:
    label: str
    target_path: Path
    sort_order: int


@dataclass(frozen=True)
class DocumentSyncResult:
    docs_dir: Path
    indexed_document_ids: list[str]
    link_count: int
    pruned_document_ids: list[str] = field(default_factory=list)


FRONT_MATTER_PATTERN = re.compile(r"\A---\s*\n(?P<meta>.*?)\n---\s*\n?", re.DOTALL)
HEADING_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
MARKDOWN_LINK_PATTERN = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def sync_markdown_documents(
    session: Session,
    *,
    project: Project,
    docs_dir: str,
    prune: bool = False,
) -> DocumentSyncResult:
    resolved_docs_dir = _resolve_docs_dir(docs_dir, project=project)
    markdown_documents = _load_markdown_documents(resolved_docs_dir)
    path_to_doc_id = {
        document.source_path.resolve(strict=False): document.doc_id
        for document in markdown_documents
    }

    indexed_document_ids: list[str] = []
    for markdown_document in markdown_documents:
        upsert_document(
            session,
            project=project,
            document=DocumentCreate(
                id=markdown_document.doc_id,
                title=markdown_document.title,
                source_path=str(markdown_document.display_source_path),
                doc_type=markdown_document.doc_type,
                area=markdown_document.area,
                tags=markdown_document.tags,
                content_markdown=markdown_document.content_markdown,
            ),
        )
        indexed_document_ids.append(markdown_document.doc_id)

    session.flush()
    session.execute(
        delete(DocumentLink).where(DocumentLink.source_document_id.in_(indexed_document_ids))
    )

    link_count = 0
    for markdown_document in markdown_documents:
        for link in _extract_markdown_links(markdown_document):
            session.add(
                DocumentLink(
                    source_document_id=markdown_document.doc_id,
                    target_document_id=path_to_doc_id.get(link.target_path.resolve(strict=False)),
                    target_path=str(_to_display_path(link.target_path)),
                    label=link.label,
                    relation_type="markdown_link",
                    sort_order=link.sort_order,
                )
            )
            link_count += 1

    pruned_document_ids: list[str] = []
    if prune:
        pruned_document_ids = _prune_project_documents(
            session=session,
            project=project,
            keep_document_ids=set(indexed_document_ids),
        )

    session.flush()
    return DocumentSyncResult(
        docs_dir=resolved_docs_dir,
        indexed_document_ids=indexed_document_ids,
        link_count=link_count,
        pruned_document_ids=pruned_document_ids,
    )


def _resolve_docs_dir(docs_dir: str, *, project: Project) -> Path:
    path = Path(docs_dir).expanduser()
    if path.is_absolute():
        mapped_path = _to_container_path(path)
        return mapped_path if mapped_path.exists() else path

    candidates = [
        *[project_root / path for project_root in _project_root_candidates(project)],
        Path.cwd() / path,
        Path.cwd().parent / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _load_markdown_documents(docs_dir: Path) -> list[MarkdownDocument]:
    if not docs_dir.exists():
        raise FileNotFoundError(f"Docs directory not found: {docs_dir}")
    if not docs_dir.is_dir():
        raise NotADirectoryError(f"Docs path is not a directory: {docs_dir}")

    documents: list[MarkdownDocument] = []
    for path in _iter_markdown_paths(docs_dir):
        parsed = _parse_markdown_document(path)
        if parsed is not None:
            documents.append(parsed)
    return documents


def _iter_markdown_paths(docs_dir: Path) -> list[Path]:
    root_agent = docs_dir / "AGENTS.md"
    docs_child_dir = docs_dir / "docs"
    if root_agent.exists() and docs_child_dir.is_dir():
        return [root_agent, *sorted(docs_child_dir.rglob("*.md"))]
    return sorted(docs_dir.rglob("*.md"))


def _parse_markdown_document(path: Path) -> MarkdownDocument | None:
    raw_content = path.read_text(encoding="utf-8")
    match = FRONT_MATTER_PATTERN.match(raw_content)
    if match is None:
        return None

    metadata = _parse_front_matter(match.group("meta"))
    doc_id = metadata.get("doc_id")
    if not doc_id:
        return None

    content = raw_content[match.end() :].lstrip()
    title = metadata.get("title") or _first_heading(content) or path.stem.replace("-", " ").title()
    return MarkdownDocument(
        doc_id=doc_id,
        title=title,
        source_path=path,
        display_source_path=_to_display_path(path),
        doc_type=metadata.get("doc_type") or "readme",
        area=metadata.get("area"),
        tags=_parse_tags(metadata.get("tags")),
        content_markdown=content,
    )


def _parse_front_matter(raw_metadata: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in raw_metadata.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata


def _parse_tags(raw_tags: str | None) -> list[str]:
    if not raw_tags:
        return []
    tags = raw_tags.strip()
    if tags.startswith("[") and tags.endswith("]"):
        tags = tags[1:-1]
    return [tag.strip().strip('"').strip("'") for tag in tags.split(",") if tag.strip()]


def _first_heading(content: str) -> str | None:
    match = HEADING_PATTERN.search(content)
    if match is None:
        return None
    return match.group(1).strip()


def _extract_markdown_links(document: MarkdownDocument) -> list[MarkdownLink]:
    links: list[MarkdownLink] = []
    for match in MARKDOWN_LINK_PATTERN.finditer(document.content_markdown):
        target = match.group(2).strip()
        if _is_external_or_anchor_link(target):
            continue
        target_without_fragment = target.split("#", 1)[0]
        if not target_without_fragment.endswith(".md"):
            continue
        target_path = document.source_path.parent / unquote(target_without_fragment)
        links.append(
            MarkdownLink(
                label=match.group(1).strip(),
                target_path=target_path.resolve(strict=False),
                sort_order=len(links),
            )
        )
    return links


def _is_external_or_anchor_link(target: str) -> bool:
    lowered = target.lower()
    return (
        lowered.startswith("#")
        or lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("mailto:")
    )


def _prune_project_documents(
    *,
    session: Session,
    project: Project,
    keep_document_ids: set[str],
) -> list[str]:
    existing_ids = set(
        session.scalars(select(Document.id).where(Document.project_id == project.id)).all()
    )
    stale_ids = sorted(existing_ids - keep_document_ids)
    if not stale_ids:
        return []

    session.execute(
        delete(DocumentLink).where(
            DocumentLink.source_document_id.in_(stale_ids)
            | DocumentLink.target_document_id.in_(stale_ids)
        )
    )
    session.execute(delete(RetrievalHit).where(RetrievalHit.document_id.in_(stale_ids)))
    session.execute(delete(Document).where(Document.id.in_(stale_ids)))
    return stale_ids


def _project_root_candidates(project: Project) -> list[Path]:
    if not project.root_path:
        return []

    host_root = Path(project.root_path).expanduser()
    candidates = [host_root]
    mapped_root = _to_container_path(host_root)
    if mapped_root != host_root:
        candidates.insert(0, mapped_root)
    return candidates


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


def _to_display_path(path: Path) -> Path:
    host_root = settings.workspace_host_root
    container_root = settings.workspace_container_root
    if not host_root or not container_root:
        return path

    try:
        relative = path.resolve(strict=False).relative_to(
            Path(container_root).expanduser().resolve(strict=False)
        )
    except ValueError:
        return path
    return Path(host_root).expanduser() / relative
