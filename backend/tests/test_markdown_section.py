import pytest

from context_router.services.markdown_section import (
    MarkdownSectionError,
    extract_markdown_section,
)


def test_extracts_heading_and_nested_content() -> None:
    content = "# 文档\n\n## 启动\n正文\n\n### Docker\n命令\n\n## 测试\n结束\n"

    result = extract_markdown_section(content, "启动")

    assert result == "## 启动\n正文\n\n### Docker\n命令\n"


def test_ignores_heading_inside_fenced_code() -> None:
    content = "# 文档\n\n```md\n## 启动\n```\n\n## 启动\n真实内容\n"

    result = extract_markdown_section(content, "启动")

    assert result == "## 启动\n真实内容\n"


def test_missing_section_has_stable_error_code() -> None:
    with pytest.raises(MarkdownSectionError) as raised:
        extract_markdown_section("# 文档\n", "启动")

    assert raised.value.code == "section_not_found"


def test_duplicate_section_is_ambiguous() -> None:
    with pytest.raises(MarkdownSectionError) as raised:
        extract_markdown_section("## 启动\n一\n## 启动\n二\n", "启动")

    assert raised.value.code == "section_ambiguous"
