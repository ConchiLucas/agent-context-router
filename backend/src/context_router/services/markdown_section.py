from __future__ import annotations

import re

ATX_HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*\r?\n?$")
TRAILING_HASHES_PATTERN = re.compile(r"[ \t]+#+[ \t]*$")
FENCE_PATTERN = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


class MarkdownSectionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def extract_markdown_section(content: str, section: str) -> str:
    normalized_section = section.strip()
    if not normalized_section:
        raise MarkdownSectionError("invalid_section", "section 不能为空")

    lines = content.splitlines(keepends=True)
    headings: list[tuple[int, int, str]] = []
    fence_character: str | None = None
    fence_length = 0

    for index, line in enumerate(lines):
        fence_match = FENCE_PATTERN.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = None
                fence_length = 0
            continue

        if fence_character is not None:
            continue

        heading_match = ATX_HEADING_PATTERN.match(line)
        if not heading_match:
            continue
        heading_text = TRAILING_HASHES_PATTERN.sub("", heading_match.group(2)).strip()
        headings.append((index, len(heading_match.group(1)), heading_text))

    matches = [heading for heading in headings if heading[2] == normalized_section]
    if not matches:
        raise MarkdownSectionError(
            "section_not_found",
            f"找不到章节：{normalized_section}",
        )
    if len(matches) > 1:
        raise MarkdownSectionError(
            "section_ambiguous",
            f"章节标题重复：{normalized_section}",
        )

    start_index, start_level, _ = matches[0]
    end_index = len(lines)
    for heading_index, heading_level, _ in headings:
        if heading_index > start_index and heading_level <= start_level:
            end_index = heading_index
            break

    return "".join(lines[start_index:end_index]).rstrip() + "\n"
