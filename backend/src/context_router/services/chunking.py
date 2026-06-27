from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MarkdownChunk:
    heading_path: list[str]
    chunk_index: int
    content: str
    token_estimate: int
    metadata: dict[str, Any] = field(default_factory=dict)


def chunk_markdown(markdown: str, max_chars: int = 1400) -> list[MarkdownChunk]:
    sections = _collect_sections(markdown)
    chunks: list[MarkdownChunk] = []

    for heading_path, content in sections:
        for piece in _split_content(content, max_chars=max_chars):
            normalized = piece.strip()
            if not normalized:
                continue
            chunks.append(
                MarkdownChunk(
                    heading_path=list(heading_path),
                    chunk_index=len(chunks),
                    content=normalized,
                    token_estimate=max(1, len(normalized.split())),
                )
            )

    return chunks


def _collect_sections(markdown: str) -> list[tuple[list[str], str]]:
    heading_path: list[str] = []
    lines: list[str] = []
    sections: list[tuple[list[str], str]] = []

    def flush() -> None:
        content = "\n".join(lines).strip()
        if content:
            sections.append((list(heading_path), content))
        lines.clear()

    for raw_line in markdown.splitlines():
        heading = _parse_heading(raw_line)
        if heading is None:
            lines.append(raw_line)
            continue

        flush()
        level, title = heading
        heading_path[:] = heading_path[: level - 1]
        heading_path.append(title)

    flush()

    if not sections and markdown.strip():
        sections.append(([], markdown.strip()))

    return sections


def _parse_heading(line: str) -> tuple[int, str] | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None

    hashes, _, title = stripped.partition(" ")
    if not title or any(character != "#" for character in hashes):
        return None

    level = len(hashes)
    if level > 6:
        return None

    return level, title.strip()


def _split_content(content: str, max_chars: int) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in content.split("\n\n") if paragraph.strip()]
    pieces: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_split_long_paragraph(paragraph, max_chars=max_chars))
            continue

        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                pieces.append(current)
            current = paragraph

    if current:
        pieces.append(current)

    return pieces


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    words = paragraph.split()
    pieces: list[str] = []
    current = ""

    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                pieces.append(current)
            current = word

    if current:
        pieces.append(current)

    return pieces
