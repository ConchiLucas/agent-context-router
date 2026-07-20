from context_router.services.document_metadata import parse_document_metadata


def test_reads_explicit_title_and_summary() -> None:
    metadata = parse_document_metadata(
        """---
title: 启动与开发规范
summary: 说明启动、测试和构建方式。
---

# 正文标题
"""
    )

    assert metadata.title == "启动与开发规范"
    assert metadata.summary == "说明启动、测试和构建方式。"
    assert metadata.error is None


def test_does_not_fallback_to_heading_or_first_paragraph() -> None:
    metadata = parse_document_metadata("# 数据库信息\n\n这里是第一段正文。")

    assert metadata.title is None
    assert metadata.summary is None
    assert metadata.error is None


def test_allows_title_without_summary() -> None:
    metadata = parse_document_metadata("---\ntitle: 普通文档\n---\n\n正文")

    assert metadata.title == "普通文档"
    assert metadata.summary is None


def test_reports_invalid_yaml_without_fallback() -> None:
    metadata = parse_document_metadata("---\ntitle: bad: yaml\n---\n\n# 标题")

    assert metadata.title is None
    assert metadata.summary is None
    assert metadata.error == "Front Matter 不是合法 YAML"
