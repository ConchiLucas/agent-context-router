from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from context_router.schemas.projects import DocumentDetail, DocumentTreeNode

CHILDREN_HEADING = "## 下级文档"
TABLE_HEADER = ("功能说明", "相对路径")
TABLE_SEPARATOR_PATTERN = re.compile(r"^:?-{3,}:?$")
MARKDOWN_LINK_PATTERN = re.compile(r"^\[[^\]]+\]\(([^)]+)\)$")


class DocumentTreeError(ValueError):
    pass


@dataclass(slots=True)
class ChildMapping:
    description: str
    relative_path: str


@dataclass(slots=True)
class CachedDocument:
    id: str
    description: str
    path: str
    relative_path: str | None
    content: str
    error: str | None = None

    def to_detail(self) -> DocumentDetail:
        return DocumentDetail(
            id=self.id,
            description=self.description,
            path=self.path,
            relative_path=self.relative_path,
            content=self.content,
            error=self.error,
        )


@dataclass(slots=True)
class CachedTreeNode:
    id: str
    description: str
    path: str
    relative_path: str | None
    error: str | None = None
    children: list[CachedTreeNode] = field(default_factory=list)

    def to_schema(self) -> DocumentTreeNode:
        return DocumentTreeNode(
            id=self.id,
            description=self.description,
            path=self.path,
            relative_path=self.relative_path,
            error=self.error,
            children=[child.to_schema() for child in self.children],
        )


@dataclass(slots=True)
class DocumentCache:
    root: CachedTreeNode
    documents: dict[str, CachedDocument]


def _table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _clean_relative_path(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] == "`":
        cleaned = cleaned[1:-1].strip()

    markdown_link = MARKDOWN_LINK_PATTERN.fullmatch(cleaned)
    if markdown_link:
        cleaned = markdown_link.group(1).strip()

    return cleaned


def parse_child_mappings(content: str) -> list[ChildMapping]:
    """Parse the two-column table directly below the first 下级文档 heading."""
    lines = content.splitlines()
    try:
        heading_index = next(
            index for index, line in enumerate(lines) if line.strip() == CHILDREN_HEADING
        )
    except StopIteration:
        return []

    table_start: int | None = None
    for index in range(heading_index + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("## "):
            break
        if tuple(_table_cells(lines[index])) == TABLE_HEADER:
            table_start = index
            break

    if table_start is None or table_start + 1 >= len(lines):
        raise DocumentTreeError("“下级文档”缺少“功能说明 / 相对路径”表格")

    separators = _table_cells(lines[table_start + 1])
    if len(separators) != 2 or not all(
        TABLE_SEPARATOR_PATTERN.fullmatch(value) for value in separators
    ):
        raise DocumentTreeError("“下级文档”表格分隔行格式不正确")

    mappings: list[ChildMapping] = []
    seen_paths: set[str] = set()
    for line in lines[table_start + 2 :]:
        cells = _table_cells(line)
        if not cells:
            break
        if len(cells) != 2:
            raise DocumentTreeError("“下级文档”中的每行必须正好包含两列")

        description, raw_path = cells
        relative_path = _clean_relative_path(raw_path)
        if not description or not relative_path:
            raise DocumentTreeError("“下级文档”的功能说明和相对路径不能为空")
        if relative_path in seen_paths:
            raise DocumentTreeError(f"下级路径重复：{relative_path}")

        seen_paths.add(relative_path)
        mappings.append(
            ChildMapping(
                description=description,
                relative_path=relative_path,
            )
        )

    return mappings


def _document_id(path: Path) -> str:
    return hashlib.sha256(str(path).encode()).hexdigest()[:20]


def _error_document_id(parent_path: Path, relative_path: str) -> str:
    source = f"{parent_path}\0{relative_path}"
    return hashlib.sha256(source.encode()).hexdigest()[:20]


def build_document_cache(root_path: Path) -> DocumentCache:
    resolved_root = root_path.resolve()
    if resolved_root.name != "AGENTS.md":
        raise DocumentTreeError("项目入口文件必须命名为 AGENTS.md")
    if not resolved_root.is_file():
        raise DocumentTreeError(f"入口文件不存在：{root_path}")

    documents: dict[str, CachedDocument] = {}

    def error_node(
        *,
        parent_path: Path,
        description: str,
        relative_path: str,
        path: Path,
        message: str,
    ) -> CachedTreeNode:
        node_id = _error_document_id(parent_path, relative_path)
        path_text = str(path)
        documents[node_id] = CachedDocument(
            id=node_id,
            description=description,
            path=path_text,
            relative_path=relative_path,
            content="",
            error=message,
        )
        return CachedTreeNode(
            id=node_id,
            description=description,
            path=path_text,
            relative_path=relative_path,
            error=message,
        )

    def walk(
        current_path: Path,
        *,
        description: str,
        relative_path: str | None,
        ancestors: frozenset[Path],
    ) -> CachedTreeNode:
        current_path = current_path.resolve()
        node_id = _document_id(current_path)

        if current_path in ancestors:
            return CachedTreeNode(
                id=node_id,
                description=description,
                path=str(current_path),
                relative_path=relative_path,
                error="检测到循环引用，已停止递归",
            )

        try:
            content = current_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            message = f"无法读取文档：{exc}"
            documents[node_id] = CachedDocument(
                id=node_id,
                description=description,
                path=str(current_path),
                relative_path=relative_path,
                content="",
                error=message,
            )
            return CachedTreeNode(
                id=node_id,
                description=description,
                path=str(current_path),
                relative_path=relative_path,
                error=message,
            )

        document = CachedDocument(
            id=node_id,
            description=description,
            path=str(current_path),
            relative_path=relative_path,
            content=content,
        )
        documents[node_id] = document

        try:
            mappings = parse_child_mappings(content)
        except DocumentTreeError as exc:
            document.error = str(exc)
            return CachedTreeNode(
                id=node_id,
                description=description,
                path=str(current_path),
                relative_path=relative_path,
                error=str(exc),
            )

        node = CachedTreeNode(
            id=node_id,
            description=description,
            path=str(current_path),
            relative_path=relative_path,
        )
        next_ancestors = ancestors | {current_path}
        allowed_root = current_path.parent.resolve()

        for mapping in mappings:
            declared_path = Path(mapping.relative_path)
            if declared_path.is_absolute() or not mapping.relative_path.startswith("./"):
                node.children.append(
                    error_node(
                        parent_path=current_path,
                        description=mapping.description,
                        relative_path=mapping.relative_path,
                        path=declared_path,
                        message="下级文档必须使用以 ./ 开头的相对路径",
                    )
                )
                continue

            child_path = (allowed_root / declared_path).resolve()
            try:
                child_path.relative_to(allowed_root)
            except ValueError:
                node.children.append(
                    error_node(
                        parent_path=current_path,
                        description=mapping.description,
                        relative_path=mapping.relative_path,
                        path=child_path,
                        message="下级文档不能越出当前文档所在目录",
                    )
                )
                continue

            if child_path.suffix.lower() != ".md":
                node.children.append(
                    error_node(
                        parent_path=current_path,
                        description=mapping.description,
                        relative_path=mapping.relative_path,
                        path=child_path,
                        message="下级路径必须指向 Markdown 文件",
                    )
                )
                continue

            if not child_path.is_file():
                node.children.append(
                    error_node(
                        parent_path=current_path,
                        description=mapping.description,
                        relative_path=mapping.relative_path,
                        path=child_path,
                        message="文档文件不存在",
                    )
                )
                continue

            node.children.append(
                walk(
                    child_path,
                    description=mapping.description,
                    relative_path=mapping.relative_path,
                    ancestors=next_ancestors,
                )
            )

        return node

    root = walk(
        resolved_root,
        description="项目文档入口",
        relative_path=None,
        ancestors=frozenset(),
    )
    return DocumentCache(root=root, documents=documents)
