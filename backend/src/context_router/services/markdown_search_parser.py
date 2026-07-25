from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from context_router.services.document_metadata import FRONT_MATTER_PATTERN
from context_router.services.markdown_section import (
    ATX_HEADING_PATTERN,
    TRAILING_HASHES_PATTERN,
)

DEFAULT_MAX_CHUNK_CHARS = 8_000
DEFAULT_OVERLAP_CHARS = 200

FENCE_LINE_PATTERN = re.compile(r"^[ \t]{0,3}(?P<marker>`{3,}|~{3,})(?P<remainder>.*)$")
BLOCKQUOTE_PATTERN = re.compile(r"^(?:[ \t]*>[ \t]?)+")
LIST_MARKER_PATTERN = re.compile(r"^[ \t]*(?:[-+*]|\d+[.)])[ \t]+")
TASK_MARKER_PATTERN = re.compile(r"^\[[ xX]\][ \t]+")
INLINE_LINK_PATTERN = re.compile(r"!?\[([^\]]*)\]\(([^)\n]+)\)")
INLINE_CODE_PATTERN = re.compile(r"(`+)(.+?)\1")
TABLE_SEPARATOR_PATTERN = re.compile(
    r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)+\|?[ \t]*$"
)
HORIZONTAL_RULE_PATTERN = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$")
MULTIPLE_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")
WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class MarkdownSearchChunk:
    """A non-overlapping Markdown section split into bounded searchable chunks."""

    section: str | None
    section_path: tuple[str, ...]
    section_ordinal: int
    section_readable: bool
    chunk_index: int
    body_text: str


@dataclass(slots=True)
class _BodyLine:
    value: str
    is_code: bool = False


@dataclass(slots=True)
class _ParsedSection:
    section: str | None
    section_path: tuple[str, ...]
    section_ordinal: int
    body_lines: list[_BodyLine]


def normalize_search_text(value: str) -> str:
    """Normalize a query or combined index value for case-insensitive fuzzy search."""

    normalized = unicodedata.normalize("NFKC", value).lower()
    return WHITESPACE_PATTERN.sub(" ", normalized).strip()


def parse_markdown_search_chunks(
    content: str,
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[MarkdownSearchChunk]:
    """Parse Markdown into section-aware chunks suitable for the PostgreSQL index.

    ATX headings inside fenced code blocks remain body text instead of becoming
    sections. Leading YAML Front Matter and fence marker lines are excluded.
    """

    _validate_chunk_limits(max_chunk_chars, overlap_chars)
    content_without_front_matter = _remove_front_matter(content)
    sections = _parse_sections(content_without_front_matter)
    heading_counts = Counter(section.section for section in sections if section.section is not None)
    has_heading = any(section.section is not None for section in sections)

    chunks: list[MarkdownSearchChunk] = []
    for parsed_section in sections:
        body_text = _body_text(parsed_section.body_lines)
        if parsed_section.section is None and has_heading and not body_text:
            continue

        section_readable = (
            parsed_section.section is not None and heading_counts[parsed_section.section] == 1
        )
        body_chunks = _split_with_overlap(
            body_text,
            max_chunk_chars=max_chunk_chars,
            overlap_chars=overlap_chars,
        )
        for chunk_index, chunk_text in enumerate(body_chunks):
            chunks.append(
                MarkdownSearchChunk(
                    section=parsed_section.section,
                    section_path=parsed_section.section_path,
                    section_ordinal=parsed_section.section_ordinal,
                    section_readable=section_readable,
                    chunk_index=chunk_index,
                    body_text=chunk_text,
                )
            )

    return chunks


def _validate_chunk_limits(max_chunk_chars: int, overlap_chars: int) -> None:
    if max_chunk_chars <= 0:
        raise ValueError("max_chunk_chars 必须大于 0")
    if overlap_chars < 0:
        raise ValueError("overlap_chars 不能小于 0")
    if overlap_chars >= max_chunk_chars:
        raise ValueError("overlap_chars 必须小于 max_chunk_chars")


def _remove_front_matter(content: str) -> str:
    match = FRONT_MATTER_PATTERN.match(content)
    return content[match.end() :] if match is not None else content


def _parse_sections(content: str) -> list[_ParsedSection]:
    sections = [
        _ParsedSection(
            section=None,
            section_path=(),
            section_ordinal=0,
            body_lines=[],
        )
    ]
    heading_stack: list[tuple[int, str]] = []
    fence_character: str | None = None
    fence_length = 0
    section_ordinal = 0

    for line in content.splitlines():
        fence_match = FENCE_LINE_PATTERN.match(line)
        if fence_match is not None:
            marker = fence_match.group("marker")
            remainder = fence_match.group("remainder")
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
                continue
            if (
                marker[0] == fence_character
                and len(marker) >= fence_length
                and not remainder.strip()
            ):
                fence_character = None
                fence_length = 0
                continue

        if fence_character is not None:
            sections[-1].body_lines.append(_BodyLine(line, is_code=True))
            continue

        heading_match = ATX_HEADING_PATTERN.match(line)
        if heading_match is None:
            sections[-1].body_lines.append(_BodyLine(line))
            continue

        heading_level = len(heading_match.group(1))
        heading_text = TRAILING_HASHES_PATTERN.sub("", heading_match.group(2)).strip()
        while heading_stack and heading_stack[-1][0] >= heading_level:
            heading_stack.pop()
        heading_stack.append((heading_level, heading_text))

        section_ordinal += 1
        sections.append(
            _ParsedSection(
                section=heading_text,
                section_path=tuple(title for _, title in heading_stack),
                section_ordinal=section_ordinal,
                body_lines=[],
            )
        )

    return sections


def _body_text(lines: list[_BodyLine]) -> str:
    normalized_lines: list[str] = []
    for body_line in lines:
        if body_line.is_code:
            normalized_lines.append(body_line.value.rstrip())
            continue

        line = body_line.value.rstrip()
        if TABLE_SEPARATOR_PATTERN.fullmatch(line) or HORIZONTAL_RULE_PATTERN.fullmatch(line):
            continue

        line = BLOCKQUOTE_PATTERN.sub("", line)
        line = LIST_MARKER_PATTERN.sub("", line)
        line = TASK_MARKER_PATTERN.sub("", line)
        line = INLINE_LINK_PATTERN.sub(
            lambda match: f"{match.group(1)} {match.group(2)}".strip(),
            line,
        )
        line = INLINE_CODE_PATTERN.sub(lambda match: match.group(2), line)
        if "|" in line:
            line = " ".join(part.strip() for part in line.strip("|").split("|"))
        normalized_lines.append(line)

    text = "\n".join(normalized_lines).strip()
    text = MULTIPLE_BLANK_LINES_PATTERN.sub("\n\n", text)
    return unicodedata.normalize("NFKC", text)


def _split_with_overlap(
    text: str,
    *,
    max_chunk_chars: int,
    overlap_chars: int,
) -> list[str]:
    if len(text) <= max_chunk_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    text_length = len(text)
    while start < text_length:
        hard_end = min(start + max_chunk_chars, text_length)
        end = hard_end
        if hard_end < text_length:
            minimum_break = start + max(max_chunk_chars // 2, overlap_chars + 1)
            for separator in ("\n\n", "\n", " "):
                candidate = text.rfind(separator, minimum_break, hard_end)
                if candidate >= minimum_break:
                    end = candidate + len(separator)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_length:
            break

        next_start = max(end - overlap_chars, start + 1)
        start = next_start

    return chunks or [""]
