from typer.testing import CliRunner

from context_router.cli import app


def test_project_add_posts_payload(monkeypatch) -> None:
    runner = CliRunner()

    def fake_post_json(path: str, payload: dict) -> dict:
        assert path == "/api/projects"
        assert payload == {
            "slug": "my-app",
            "name": "My App",
            "root_path": "/repo/my-app",
            "description": "",
        }
        return {"slug": "my-app", "name": "My App", "id": "project-id"}

    monkeypatch.setattr("context_router.cli._post_json", fake_post_json)

    result = runner.invoke(
        app,
        ["project", "add", "--slug", "my-app", "--name", "My App", "--root-path", "/repo/my-app"],
    )

    assert result.exit_code == 0
    assert "my-app" in result.stdout


def test_doc_add_reads_markdown_file_and_posts_payload(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    markdown_path = tmp_path / "payments.md"
    markdown_path.write_text("# Payments\nRun tests.", encoding="utf-8")

    def fake_post_json(path: str, payload: dict) -> dict:
        assert path == "/api/projects/my-app/documents"
        assert payload["id"] == "payments-runbook"
        assert payload["content_markdown"] == "# Payments\nRun tests."
        return {"id": "payments-runbook", "chunk_count": 1, "status": "active"}

    monkeypatch.setattr("context_router.cli._post_json", fake_post_json)

    result = runner.invoke(
        app,
        [
            "doc",
            "add",
            "--project",
            "my-app",
            "--id",
            "payments-runbook",
            "--type",
            "runbook",
            "--area",
            "payments",
            str(markdown_path),
        ],
    )

    assert result.exit_code == 0
    assert "payments-runbook" in result.stdout


def test_prepare_command_prints_markdown_response(monkeypatch) -> None:
    runner = CliRunner()

    def fake_post_json(path: str, payload: dict) -> dict:
        assert path == "/api/context/prepare"
        assert payload["project"] == "my-app"
        assert payload["task"] == "fix payments"
        return {"markdown": "trace_id: ctx_001\n\n## Required Context"}

    monkeypatch.setattr("context_router.cli._post_json", fake_post_json)

    result = runner.invoke(app, ["prepare", "--project", "my-app", "--task", "fix payments"])

    assert result.exit_code == 0
    assert "trace_id: ctx_001" in result.stdout


def test_read_command_requires_reason_and_prints_document(monkeypatch) -> None:
    runner = CliRunner()

    def fake_get_json(path: str, params: dict) -> dict:
        assert path == "/api/documents/payments-runbook"
        assert params["trace_id"] == "ctx_001"
        assert params["reason"] == "Need full runbook"
        return {
            "id": "payments-runbook",
            "title": "Payments runbook",
            "content_markdown": "# Payments\nRun tests.",
        }

    monkeypatch.setattr("context_router.cli._get_json", fake_get_json)

    result = runner.invoke(
        app,
        [
            "read",
            "payments-runbook",
            "--trace",
            "ctx_001",
            "--reason",
            "Need full runbook",
        ],
    )

    assert result.exit_code == 0
    assert "# Payments" in result.stdout


def test_trace_command_prints_trace_summary(monkeypatch) -> None:
    runner = CliRunner()

    def fake_get_json(path: str, params: dict) -> dict:
        assert path == "/api/traces/ctx_001"
        assert params == {}
        return {
            "id": "ctx_001",
            "project": {"slug": "my-app", "name": "My App"},
            "task": "fix payments",
            "retrieval_hits": [
                {
                    "document_id": "payments-runbook",
                    "document_title": "Payments runbook",
                    "rank": 1,
                    "score": 8.5,
                    "reason": "Matched payments.",
                    "feedback": "useful",
                }
            ],
            "events": [
                {"event_type": "prepare", "payload": {}},
                {
                    "event_type": "read",
                    "payload": {
                        "document_id": "payments-runbook",
                        "reason": "Need details",
                    },
                },
            ],
        }

    monkeypatch.setattr("context_router.cli._get_json", fake_get_json)

    result = runner.invoke(app, ["trace", "ctx_001"])

    assert result.exit_code == 0
    assert "Trace ctx_001" in result.stdout
    assert "fix payments" in result.stdout
    assert "payments-runbook" in result.stdout
    assert "Need details" in result.stdout


def test_trace_command_can_print_json(monkeypatch) -> None:
    runner = CliRunner()

    def fake_get_json(path: str, params: dict) -> dict:
        assert path == "/api/traces/ctx_001"
        assert params == {}
        return {"id": "ctx_001", "task": "fix payments", "retrieval_hits": [], "events": []}

    monkeypatch.setattr("context_router.cli._get_json", fake_get_json)

    result = runner.invoke(app, ["trace", "ctx_001", "--json"])

    assert result.exit_code == 0
    assert '"id": "ctx_001"' in result.stdout
