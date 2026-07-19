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


def test_project_init_index_writes_short_routing_file(tmp_path) -> None:
    runner = CliRunner()
    output = tmp_path / "AI_CONTEXT_INDEX.md"

    result = runner.invoke(
        app,
        [
            "project",
            "init-index",
            "--project",
            "my-app",
            "--area",
            "payments",
            "--area",
            "build",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    content = output.read_text(encoding="utf-8")
    assert "ctx read <payments-doc-id>" in content
    assert "ctx read <build-doc-id>" in content
    assert "ctx prepare --project my-app" in content
    assert "--entrypoint-path" not in content


def test_project_init_index_refuses_to_overwrite_without_force(tmp_path) -> None:
    runner = CliRunner()
    output = tmp_path / "AI_CONTEXT_INDEX.md"
    output.write_text("existing", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "project",
            "init-index",
            "--project",
            "my-app",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code != 0
    assert "already exists" in result.output
    assert output.read_text(encoding="utf-8") == "existing"


def test_doc_add_reads_markdown_file_and_posts_payload(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    markdown_path = tmp_path / "payments.md"
    markdown_path.write_text("# Payments\nRun tests.", encoding="utf-8")

    def fake_post_json(path: str, payload: dict) -> dict:
        assert path == "/api/projects/my-app/documents"
        assert payload["id"] == "payments-runbook"
        assert payload["content_markdown"] == "# Payments\nRun tests."
        return {"id": "payments-runbook", "status": "active"}

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


def test_prepare_command_prints_markdown_response(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "ctx-state.json"
    monkeypatch.setenv("CTX_STATE_FILE", str(state_file))

    def fake_post_json(path: str, payload: dict) -> dict:
        assert path == "/api/context/prepare"
        assert payload["project"] == "my-app"
        assert payload["task"] == ""
        assert payload["area"] == "payments"
        assert payload["entrypoint_path"] == "AI_CONTEXT_INDEX.md"
        assert payload["entrypoint_rule"] == "payments tasks"
        assert payload["route_hint"] == "payments"
        assert payload["source"] == "cli"
        assert payload["agent_name"] == "codex"
        return {
            "trace_id": "ctx_001",
            "project": "my-app",
            "area": "payments",
            "markdown": "project: my-app\n\n## Required Context",
        }

    monkeypatch.setattr("context_router.cli._post_json", fake_post_json)

    result = runner.invoke(
        app,
        [
            "prepare",
            "--project",
            "my-app",
            "--area",
            "payments",
            "--entrypoint-path",
            "AI_CONTEXT_INDEX.md",
            "--entrypoint-rule",
            "payments tasks",
            "--route-hint",
            "payments",
            "--agent-name",
            "codex",
        ],
    )

    assert result.exit_code == 0
    assert "project: my-app" in result.stdout
    assert "ctx_001" in state_file.read_text(encoding="utf-8")


def test_read_command_uses_current_trace_and_prints_document(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "ctx-state.json"
    state_file.write_text(
        '{"trace_id": "ctx_001", "last_document_id": "root-index", "depth": 1}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CTX_STATE_FILE", str(state_file))

    def fake_get_json(path: str, params: dict) -> dict:
        assert path == "/api/documents/payments-runbook"
        assert params["trace_id"] == "ctx_001"
        assert params["source"] == "cli"
        assert params["parent_document_id"] == "root-index"
        assert params["depth"] == 2
        return {
            "id": "payments-runbook",
            "trace_id": "ctx_001",
            "title": "Payments runbook",
            "content_markdown": "# Payments\nRun tests.",
        }

    monkeypatch.setattr("context_router.cli._get_json", fake_get_json)

    result = runner.invoke(
        app,
        ["read", "payments-runbook"],
    )

    assert result.exit_code == 0
    assert "# Payments" in result.stdout
    state = state_file.read_text(encoding="utf-8")
    assert "payments-runbook" in state
    assert '"depth": 2' in state


def test_read_command_starts_document_path_without_parent(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "ctx-state.json"
    monkeypatch.setenv("CTX_STATE_FILE", str(state_file))

    def fake_get_json(path: str, params: dict) -> dict:
        assert path == "/api/documents/root-index"
        assert params == {"source": "cli", "depth": 1}
        return {
            "id": "root-index",
            "trace_id": "ctx_001",
            "title": "Root index",
            "content_markdown": "# Root",
        }

    monkeypatch.setattr("context_router.cli._get_json", fake_get_json)

    result = runner.invoke(app, ["read", "root-index"])

    assert result.exit_code == 0
    state = state_file.read_text(encoding="utf-8")
    assert "ctx_001" in state
    assert "root-index" in state
    assert '"depth": 1' in state


def test_read_command_uses_session_specific_state(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    monkeypatch.setenv("CTX_STATE_DIR", str(tmp_path))

    def fake_get_json(path: str, params: dict) -> dict:
        assert path == "/api/documents/root-index"
        assert params == {"source": "cli", "depth": 1}
        return {
            "id": "root-index",
            "trace_id": "ctx_001",
            "title": "Root index",
            "content_markdown": "# Root",
        }

    monkeypatch.setattr("context_router.cli._get_json", fake_get_json)

    result = runner.invoke(app, ["read", "root-index", "--session", "codex/thread:1"])

    assert result.exit_code == 0
    state_file = tmp_path / "codex-thread-1.json"
    assert state_file.exists()
    state = state_file.read_text(encoding="utf-8")
    assert "ctx_001" in state
    assert "root-index" in state


def test_reset_command_clears_current_session(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    state_file = tmp_path / "ctx-state.json"
    state_file.write_text('{"trace_id": "ctx_001"}', encoding="utf-8")
    monkeypatch.setenv("CTX_STATE_FILE", str(state_file))

    result = runner.invoke(app, ["reset"])

    assert result.exit_code == 0
    assert "Reset ctx session" in result.stdout
    assert not state_file.exists()


def test_reset_command_can_clear_session_state(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("CTX_STATE_DIR", str(tmp_path))
    state_file = tmp_path / "codex-thread-1.json"
    state_file.write_text('{"trace_id": "ctx_001"}', encoding="utf-8")

    result = runner.invoke(app, ["reset", "--session", "codex/thread:1"])

    assert result.exit_code == 0
    assert "Reset ctx session" in result.stdout
    assert not state_file.exists()


def test_trace_command_prints_trace_summary(monkeypatch) -> None:
    runner = CliRunner()

    def fake_get_json(path: str, params: dict) -> dict:
        assert path == "/api/traces/ctx_001"
        assert params == {}
        return {
            "id": "ctx_001",
            "project": {"slug": "my-app", "name": "My App"},
            "task": "fix payments",
            "area": "payments",
            "source": "cli",
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
                        "parent_document_id": "root-index",
                        "source": "cli",
                    },
                },
            ],
        }

    monkeypatch.setattr("context_router.cli._get_json", fake_get_json)

    result = runner.invoke(app, ["trace", "ctx_001"])

    assert result.exit_code == 0
    assert "Trace ctx_001" in result.stdout
    assert "Area: payments" in result.stdout
    assert "Source: cli" in result.stdout
    assert "fix payments" in result.stdout
    assert "payments-runbook" in result.stdout
    assert "root-index" in result.stdout
    assert "cli" in result.stdout


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
