from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

FRONT_MATTER_PATTERN = re.compile(
    r"\A---[ \t]*\r?\n(?P<body>.*?)\r?\n---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class DocumentMetadata:
    title: str | None = None
    summary: str | None = None
    error: str | None = None


def _optional_text(metadata: dict[object, object], field: str) -> tuple[str | None, str | None]:
    value = metadata.get(field)
    if value is None:
        return None, None
    if not isinstance(value, str) or not value.strip():
        return None, f"Front Matter 的 {field} 必须是非空字符串"
    return value.strip(), None


def parse_document_metadata(content: str) -> DocumentMetadata:
    """Read explicit title and summary values from leading YAML Front Matter."""
    match = FRONT_MATTER_PATTERN.match(content)
    if match is None:
        return DocumentMetadata()

    try:
        raw_metadata = yaml.safe_load(match.group("body"))
    except yaml.YAMLError:
        return DocumentMetadata(error="Front Matter 不是合法 YAML")

    if raw_metadata is None:
        return DocumentMetadata()
    if not isinstance(raw_metadata, dict):
        return DocumentMetadata(error="Front Matter 必须是 YAML 对象")

    title, title_error = _optional_text(raw_metadata, "title")
    summary, summary_error = _optional_text(raw_metadata, "summary")
    errors = [error for error in (title_error, summary_error) if error]
    return DocumentMetadata(
        title=title,
        summary=summary,
        error="；".join(errors) or None,
    )
