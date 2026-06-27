from context_router.services.chunking import chunk_markdown


def test_chunk_markdown_preserves_heading_paths() -> None:
    markdown = """# Payments
Intro for payments.

## Webhooks
Webhook delivery notes.

### Timeouts
Timeout remediation notes.
"""

    chunks = chunk_markdown(markdown, max_chars=500)

    assert [chunk.heading_path for chunk in chunks] == [
        ["Payments"],
        ["Payments", "Webhooks"],
        ["Payments", "Webhooks", "Timeouts"],
    ]
    assert chunks[2].content == "Timeout remediation notes."


def test_chunk_markdown_keeps_short_unheaded_document_together() -> None:
    chunks = chunk_markdown("No headings here, just a small runbook.", max_chars=500)

    assert len(chunks) == 1
    assert chunks[0].heading_path == []
    assert chunks[0].content == "No headings here, just a small runbook."
    assert chunks[0].token_estimate > 0


def test_chunk_markdown_splits_long_sections_without_losing_heading_path() -> None:
    markdown = "# Build\n" + "\n\n".join(
        f"Paragraph {index} has build details." for index in range(6)
    )

    chunks = chunk_markdown(markdown, max_chars=70)

    assert len(chunks) > 1
    assert {tuple(chunk.heading_path) for chunk in chunks} == {("Build",)}
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
