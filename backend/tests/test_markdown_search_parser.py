import pytest

from context_router.services.markdown_search_parser import (
    MarkdownSearchChunk,
    normalize_search_text,
    parse_markdown_search_chunks,
)


def test_parses_preamble_and_nested_section_paths() -> None:
    content = (
        "项目序言\n\n# 开发\n开发说明\n## 启动\n启动说明\n### Docker\n容器说明\n## 测试\n测试说明\n"
    )

    chunks = parse_markdown_search_chunks(content)

    assert chunks == [
        MarkdownSearchChunk(None, (), 0, False, 0, "项目序言"),
        MarkdownSearchChunk("开发", ("开发",), 1, True, 0, "开发说明"),
        MarkdownSearchChunk("启动", ("开发", "启动"), 2, True, 0, "启动说明"),
        MarkdownSearchChunk(
            "Docker",
            ("开发", "启动", "Docker"),
            3,
            True,
            0,
            "容器说明",
        ),
        MarkdownSearchChunk("测试", ("开发", "测试"), 4, True, 0, "测试说明"),
    ]


def test_excludes_front_matter_and_keeps_fenced_code_content() -> None:
    content = (
        "---\n"
        "title: 不应进入正文\n"
        "summary: Front Matter 不可搜索\n"
        "---\n"
        "# 使用方法\n"
        "```md\n"
        "## 这不是章节\n"
        "client.execute(`SELECT 1`)\n"
        "```\n"
        "结束\n"
    )

    chunks = parse_markdown_search_chunks(content)

    assert len(chunks) == 1
    assert chunks[0].section == "使用方法"
    assert chunks[0].section_path == ("使用方法",)
    assert "title:" not in chunks[0].body_text
    assert "## 这不是章节" in chunks[0].body_text
    assert "client.execute(`SELECT 1`)" in chunks[0].body_text
    assert "```" not in chunks[0].body_text


def test_duplicate_heading_names_are_not_section_readable() -> None:
    content = "# 后端\n## 配置\nA\n# 前端\n## 配置\nB\n"

    chunks = parse_markdown_search_chunks(content)
    configurations = [chunk for chunk in chunks if chunk.section == "配置"]

    assert len(configurations) == 2
    assert all(not chunk.section_readable for chunk in configurations)
    assert configurations[0].section_path == ("后端", "配置")
    assert configurations[1].section_path == ("前端", "配置")


def test_unique_empty_heading_still_produces_searchable_chunk() -> None:
    chunks = parse_markdown_search_chunks("# 只有标题\n")

    assert chunks == [MarkdownSearchChunk("只有标题", ("只有标题",), 1, True, 0, "")]


def test_front_matter_only_document_still_produces_metadata_anchor_chunk() -> None:
    chunks = parse_markdown_search_chunks("---\ntitle: 只有元数据\n---\n")

    assert chunks == [MarkdownSearchChunk(None, (), 0, False, 0, "")]


def test_cleans_common_markdown_decorations_but_preserves_values() -> None:
    content = (
        "# 连接\n"
        "- [文档](./guide.md)\n"
        "> `database_name`\n"
        "| 字段 | 说明 |\n"
        "| --- | --- |\n"
        "| user_id | 用户 ID |\n"
    )

    [chunk] = parse_markdown_search_chunks(content)

    assert chunk.body_text == ("文档 ./guide.md\ndatabase_name\n字段 说明\nuser_id 用户 ID")


def test_splits_long_section_with_bounded_overlapping_chunks() -> None:
    body = " ".join(f"token-{index:03d}" for index in range(80))

    chunks = parse_markdown_search_chunks(
        f"# 长章节\n{body}\n",
        max_chunk_chars=120,
        overlap_chars=20,
    )

    assert len(chunks) > 1
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(len(chunk.body_text) <= 120 for chunk in chunks)
    assert all(chunk.section_ordinal == 1 for chunk in chunks)
    assert all(chunk.section == "长章节" for chunk in chunks)
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert any(
            previous.body_text.endswith(current.body_text[:overlap]) for overlap in range(20, 4, -1)
        )


def test_normalizes_nfkc_case_and_search_whitespace() -> None:
    assert normalize_search_text("  ＰｏｓｔｇｒｅＳＱＬ\n　迁移  ") == "postgresql 迁移"

    [chunk] = parse_markdown_search_chunks("# 标题\nＡＢＣ１２３\n")
    assert chunk.body_text == "ABC123"


@pytest.mark.parametrize(
    ("max_chunk_chars", "overlap_chars"),
    [(0, 0), (100, -1), (100, 100), (100, 101)],
)
def test_rejects_invalid_chunk_limits(
    max_chunk_chars: int,
    overlap_chars: int,
) -> None:
    with pytest.raises(ValueError):
        parse_markdown_search_chunks(
            "正文",
            max_chunk_chars=max_chunk_chars,
            overlap_chars=overlap_chars,
        )
