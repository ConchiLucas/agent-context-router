from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from context_router.db.models import Document, DocumentLink, Project, RetrievalHit
from context_router.schemas.documents import DocumentCreate
from context_router.services.document_graph import shortest_reachable_depths
from context_router.services.document_mapping import resolve_document_root
from context_router.services.document_store import upsert_document


class MarkdownSyncError(ValueError):
    pass


@dataclass(frozen=True)
class MarkdownDocument:
    doc_id: str
    title: str
    source_path: Path
    relative_path: str
    doc_type: str
    area: str | None
    tags: list[str]
    content_markdown: str


@dataclass(frozen=True)
class MarkdownLink:
    label: str
    target_path: Path
    target_display_path: str
    sort_order: int
    is_safe_target: bool


@dataclass(frozen=True)
class DocumentSyncResult:
    docs_path: str
    indexed_document_ids: list[str]
    reachable_count: int
    orphan_count: int
    broken_link_count: int
    link_count: int
    pruned_document_ids: list[str] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        return {
            "indexed": len(self.indexed_document_ids),
            "reachable": self.reachable_count,
            "orphan": self.orphan_count,
            "broken_links": self.broken_link_count,
            "pruned": len(self.pruned_document_ids),
        }


FRONT_MATTER_PATTERN = re.compile(r"\A---\s*\n(?P<meta>.*?)\n---\s*\n?", re.DOTALL)
HEADING_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
MARKDOWN_LINK_PATTERN = re.compile(r'(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')


def sync_mapped_documents(
    session: Session,
    *,
    project: Project,
) -> DocumentSyncResult:
    document_root = resolve_document_root(project)
    markdown_documents = [
        _parse_required_document(path, document_root=document_root)
        for path in _iter_markdown_paths(document_root)
    ]
    _validate_unique_document_ids(
        session,
        project=project,
        documents=markdown_documents,
    )

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
                source_path=markdown_document.relative_path,
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

    outgoing: dict[str, list[str]] = {document_id: [] for document_id in indexed_document_ids}
    link_count = 0
    broken_link_count = 0
    for markdown_document in markdown_documents:
        for link in _extract_markdown_links(
            markdown_document,
            document_root=document_root,
        ):
            target_document_id = (
                path_to_doc_id.get(link.target_path.resolve(strict=False))
                if link.is_safe_target
                else None
            )
            if target_document_id is None:
                broken_link_count += 1
            else:
                outgoing[markdown_document.doc_id].append(target_document_id)
            session.add(
                DocumentLink(
                    source_document_id=markdown_document.doc_id,
                    target_document_id=target_document_id,
                    target_path=link.target_display_path,
                    label=link.label,
                    relation_type="markdown_link",
                    sort_order=link.sort_order,
                )
            )
            link_count += 1

    root_document = markdown_documents[0]
    depths = shortest_reachable_depths(
        root_id=root_document.doc_id,
        outgoing=outgoing,
    )
    indexed_documents = session.scalars(
        select(Document).where(Document.id.in_(indexed_document_ids))
    ).all()
    for document in indexed_documents:
        document.graph_depth = depths.get(document.id)
        document.is_reachable = document.id in depths

    pruned_document_ids = _prune_project_documents(
        session=session,
        project=project,
        keep_document_ids=set(indexed_document_ids),
    )
    session.flush()
    return DocumentSyncResult(
        docs_path=project.docs_path or "",
        indexed_document_ids=indexed_document_ids,
        reachable_count=len(depths),
        orphan_count=len(indexed_document_ids) - len(depths),
        broken_link_count=broken_link_count,
        link_count=link_count,
        pruned_document_ids=pruned_document_ids,
    )


def _iter_markdown_paths(document_root: Path) -> list[Path]:
    root_agent = document_root / "AGENTS.md"
    docs_root = document_root / "docs"
    markdown_paths: list[Path] = []
    for current_root, directory_names, file_names in os.walk(
        docs_root,
        followlinks=False,
    ):
        current_path = Path(current_root)
        directory_names[:] = sorted(
            name for name in directory_names if not (current_path / name).is_symlink()
        )
        for file_name in sorted(file_names):
            path = current_path / file_name
            if path.suffix.lower() == ".md" and path.is_file() and not path.is_symlink():
                markdown_paths.append(path)
    return [root_agent, *sorted(markdown_paths)]


def _parse_required_document(path: Path, *, document_root: Path) -> MarkdownDocument:
    try:
        raw_content = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MarkdownSyncError(
            f"Mapped Markdown file not found: {_display_path(path, document_root)}"
        ) from exc

    match = FRONT_MATTER_PATTERN.match(raw_content)
    if match is None:
        raise MarkdownSyncError(
            f"Markdown file requires front matter with doc_id: {_display_path(path, document_root)}"
        )
    metadata = _parse_front_matter(match.group("meta"))
    doc_id = metadata.get("doc_id", "").strip()
    if not doc_id:
        raise MarkdownSyncError(
            f"Markdown file requires non-empty doc_id: {_display_path(path, document_root)}"
        )

    content = raw_content[match.end() :].lstrip()
    relative_path = _display_path(path, document_root)
    return MarkdownDocument(
        doc_id=doc_id,
        title=metadata.get("title")
        or _first_heading(content)
        or path.stem.replace("-", " ").title(),
        source_path=path,
        relative_path=relative_path,
        doc_type=(
            "agent_index" if relative_path == "AGENTS.md" else metadata.get("doc_type") or "readme"
        ),
        area=metadata.get("area"),
        tags=_parse_tags(metadata.get("tags")),
        content_markdown=content,
    )


def _validate_unique_document_ids(
    session: Session,
    *,
    project: Project,
    documents: list[MarkdownDocument],
) -> None:
    counts = Counter(document.doc_id for document in documents)
    duplicates = sorted(doc_id for doc_id, count in counts.items() if count > 1)
    if duplicates:
        conflicts = [
            f"{doc_id}: "
            + ", ".join(
                document.relative_path for document in documents if document.doc_id == doc_id
            )
            for doc_id in duplicates
        ]
        raise MarkdownSyncError(f"Duplicate doc_id in mapped directory: {'; '.join(conflicts)}")

    incoming_ids = list(counts)
    conflicts = session.scalars(
        select(Document).where(
            Document.id.in_(incoming_ids),
            Document.project_id != project.id,
        )
    ).all()
    if conflicts:
        conflict = sorted(conflicts, key=lambda document: document.id)[0]
        raise MarkdownSyncError(
            f"doc_id {conflict.id} is already used by project: {conflict.project.slug}"
        )


def _extract_markdown_links(
    document: MarkdownDocument,
    *,
    document_root: Path,
) -> list[MarkdownLink]:
    links: list[MarkdownLink] = []
    for match in MARKDOWN_LINK_PATTERN.finditer(document.content_markdown):
        raw_target = match.group(2).strip()
        if _is_external_or_anchor_link(raw_target):
            continue
        decoded_target = unquote(raw_target.split("#", 1)[0])
        if not decoded_target.lower().endswith(".md"):
            continue
        unresolved_target = document.source_path.parent / decoded_target
        target_path = Path(os.path.abspath(unresolved_target))
        links.append(
            MarkdownLink(
                label=match.group(1).strip(),
                target_path=target_path,
                target_display_path=_link_display_path(
                    target_path,
                    raw_target=decoded_target,
                    document_root=document_root,
                ),
                sort_order=len(links),
                is_safe_target=_is_safe_link_target(
                    target_path,
                    document_root=document_root,
                ),
            )
        )
    return links


def _link_display_path(
    target_path: Path,
    *,
    raw_target: str,
    document_root: Path,
) -> str:
    try:
        relative = target_path.relative_to(document_root.resolve(strict=True))
    except (FileNotFoundError, ValueError):
        return raw_target
    if relative == Path("AGENTS.md"):
        return relative.as_posix()
    if not relative.parts or relative.parts[0] != "docs":
        return raw_target
    return relative.as_posix()


def _is_safe_link_target(target_path: Path, *, document_root: Path) -> bool:
    root = document_root.resolve(strict=True)
    try:
        relative = target_path.relative_to(root)
    except ValueError:
        return False
    if relative != Path("AGENTS.md") and (not relative.parts or relative.parts[0] != "docs"):
        return False

    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    return True


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
    existing_documents = session.scalars(
        select(Document).where(
            Document.project_id == project.id,
            Document.id.not_in(keep_document_ids),
            Document.status != "removed",
        )
    ).all()
    stale_ids = sorted(document.id for document in existing_documents)
    if not stale_ids:
        return []

    session.execute(
        delete(DocumentLink).where(
            DocumentLink.source_document_id.in_(stale_ids)
            | DocumentLink.target_document_id.in_(stale_ids)
        )
    )
    referenced_ids = set(
        session.scalars(
            select(RetrievalHit.document_id).where(RetrievalHit.document_id.in_(stale_ids))
        ).all()
    )
    for document in existing_documents:
        if document.id in referenced_ids:
            document.status = "removed"
            document.is_reachable = False
            document.graph_depth = None
        else:
            session.delete(document)
    return stale_ids


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
    return match.group(1).strip() if match else None


def _display_path(path: Path, document_root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(document_root.resolve(strict=True)).as_posix()
    except (FileNotFoundError, ValueError):
        return str(path)
