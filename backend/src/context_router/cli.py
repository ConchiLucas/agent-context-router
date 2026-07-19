import json
import os
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

app = typer.Typer(help="Retrieve AI task context and record document reads.")
project_app = typer.Typer(help="Manage context-router projects.")
doc_app = typer.Typer(help="Manage project documents.")
app.add_typer(project_app, name="project")
app.add_typer(doc_app, name="doc")

DEFAULT_API_URL = "http://127.0.0.1:8000"


def _api_url() -> str:
    return os.environ.get("CTX_API_URL", DEFAULT_API_URL).rstrip("/")


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(f"{_api_url()}{path}", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def _get_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
    response = httpx.get(f"{_api_url()}{path}", params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _safe_session_id(session_id: str) -> str:
    safe = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-" for char in session_id
    )
    return safe.strip("-") or "default"


def _state_path(session_id: str | None = None) -> Path:
    session = session_id or os.environ.get("CTX_SESSION_ID")
    if session:
        state_dir = os.environ.get("CTX_STATE_DIR")
        if state_dir:
            return Path(state_dir) / f"{_safe_session_id(session)}.json"
        return (
            Path.home()
            / ".cache"
            / "agent-context-router"
            / "sessions"
            / f"{_safe_session_id(session)}.json"
        )

    state_file = os.environ.get("CTX_STATE_FILE")
    if state_file:
        return Path(state_file)

    state_dir = os.environ.get("CTX_STATE_DIR")
    if state_dir:
        return Path(state_dir) / "current-session.json"

    return Path.home() / ".cache" / "agent-context-router" / "current-session.json"


def _load_state(session_id: str | None = None) -> dict[str, Any]:
    path = _state_path(session_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(
    *,
    trace_id: str,
    session_id: str | None = None,
    project: str | None = None,
    area: str | None = None,
    last_document_id: str | None = None,
    depth: int | None = None,
    reset_path: bool = False,
) -> None:
    path = _state_path(session_id)
    state = _load_state(session_id)
    state["trace_id"] = trace_id
    if project is not None:
        state["project"] = project
    if area is not None:
        state["area"] = area
    if reset_path:
        state.pop("last_document_id", None)
        state.pop("depth", None)
    if last_document_id is not None:
        state["last_document_id"] = last_document_id
    if depth is not None:
        state["depth"] = depth
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        # State is only a convenience; reads can still be tracked by the API fallback.
        return


def _render_index_template(*, project: str, areas: list[str], entrypoint_path: str) -> str:
    lines = [
        "# AI_CONTEXT_INDEX.md",
        "",
        "本文件是 AI 的上下文树索引入口，只列下一层文档和读取命令。",
        "",
        "## 使用方式",
        "",
        "- 主流程是按 doc-id 运行 `ctx read <doc-id>`。",
        "- 每份文档继续列出自己的下一层文档。",
        "- `ctx prepare` 只在无法判断 doc-id 时兜底使用。",
        "",
    ]

    if areas:
        lines.extend(["## 下一层文档", ""])
        for area in areas:
            lines.extend(
                [
                    f"- `{area}`：{area} 相关稳定说明。",
                    f"  - 读取：`ctx read <{area}-doc-id>`",
                ]
            )
        lines.append("")

    lines.extend(
        [
            "## 读取示例",
            "",
            "- `ctx read <doc-id>`",
            "",
            "## 兜底检索",
            "",
            f"- `ctx prepare --project {project}`",
            "",
            "- 源码、配置、表结构等实时内容可以直接查项目目录，不强制进入 Context Router。",
            "- 如果文档树缺少合适入口，在最终回复中说明缺口，便于后续补充索引。",
            "",
        ]
    )
    return "\n".join(lines)


@project_app.command("add")
def add_project(
    slug: Annotated[str, typer.Option("--slug", help="Stable project slug.")],
    name: Annotated[str, typer.Option("--name", help="Display name.")],
    root_path: Annotated[
        str | None,
        typer.Option("--root-path", help="Local repository path."),
    ] = None,
    description: Annotated[
        str,
        typer.Option("--description", help="Short project description."),
    ] = "",
) -> None:
    body = _post_json(
        "/api/projects",
        {
            "slug": slug,
            "name": name,
            "root_path": root_path,
            "description": description,
        },
    )
    typer.echo(f"Created project {body['slug']}")


@project_app.command("init-index")
def init_index(
    project: Annotated[str, typer.Option("--project", help="Project slug.")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Path for the generated AI context index."),
    ] = Path("AI_CONTEXT_INDEX.md"),
    areas: Annotated[
        list[str] | None,
        typer.Option("--area", help="Area route to include. Repeat for multiple areas."),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
) -> None:
    if output.exists() and not force:
        raise typer.BadParameter(f"{output} already exists; pass --force to overwrite")

    output.write_text(
        _render_index_template(project=project, areas=areas or [], entrypoint_path=output.name),
        encoding="utf-8",
    )
    typer.echo(f"Wrote {output}")


@doc_app.command("add")
def add_document(
    path: Annotated[Path, typer.Argument(exists=True, readable=True, help="Markdown file path.")],
    project: Annotated[str, typer.Option("--project", help="Project slug.")],
    document_id: Annotated[str, typer.Option("--id", help="Stable document ID.")],
    doc_type: Annotated[str, typer.Option("--type", help="Document type.")],
    area: Annotated[str | None, typer.Option("--area", help="Project area.")] = None,
    title: Annotated[str | None, typer.Option("--title", help="Document title.")] = None,
) -> None:
    content = path.read_text(encoding="utf-8")
    body = _post_json(
        f"/api/projects/{project}/documents",
        {
            "id": document_id,
            "title": title or path.stem.replace("-", " ").replace("_", " ").title(),
            "source_path": str(path),
            "doc_type": doc_type,
            "area": area,
            "tags": [],
            "content_markdown": content,
        },
    )
    typer.echo(f"Indexed document {body['id']}")


@doc_app.command("sync")
def sync_documents(
    project: Annotated[str, typer.Option("--project", help="Project slug.")],
    docs_dir: Annotated[
        str,
        typer.Option(
            "--docs-dir",
            help="Managed Markdown directory. Relative paths are resolved from project root_path.",
        ),
    ] = "docs",
    prune: Annotated[
        bool,
        typer.Option(
            "--prune",
            help="Delete project documents that are not in the local docs tree.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print JSON instead of a human-readable summary."),
    ] = False,
) -> None:
    body = _post_json(
        f"/api/projects/{project}/documents/sync-local",
        {
            "docs_dir": docs_dir,
            "prune": prune,
        },
    )
    if json_output:
        typer.echo(json.dumps(body, ensure_ascii=False, indent=2))
        return

    typer.echo(
        f"Synced {body['indexed_count']} documents and {body['link_count']} links "
        f"for {body['project_slug']} from {body['docs_dir']}"
    )
    if body["pruned_count"]:
        typer.echo(f"Pruned {body['pruned_count']} documents")


@app.command()
def prepare(
    project: Annotated[str, typer.Option("--project", help="Project slug.")],
    task: Annotated[
        str,
        typer.Option("--task", help="Optional task text for ranking."),
    ] = "",
    area: Annotated[str | None, typer.Option("--area", help="Route to a project area.")] = None,
    cwd: Annotated[str | None, typer.Option("--cwd", help="Current repository path.")] = None,
    entrypoint_path: Annotated[
        str | None,
        typer.Option("--entrypoint-path", help="Index file path that routed this task."),
    ] = None,
    entrypoint_rule: Annotated[
        str | None,
        typer.Option("--entrypoint-rule", help="Rule or heading that selected this route."),
    ] = None,
    route_hint: Annotated[
        str | None,
        typer.Option("--route-hint", help="Optional routing hint from the index document."),
    ] = None,
    session: Annotated[
        str | None,
        typer.Option("--session", help="Stable AI conversation/session ID for trace continuity."),
    ] = None,
    agent_name: Annotated[str | None, typer.Option("--agent-name", help="AI agent name.")] = None,
    max_documents: Annotated[int, typer.Option("--max-documents", min=1, max=20)] = 5,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print JSON instead of Markdown."),
    ] = False,
) -> None:
    payload = {
        "project": project,
        "task": task,
        "area": area,
        "cwd": cwd,
        "entrypoint_path": entrypoint_path,
        "entrypoint_rule": entrypoint_rule,
        "route_hint": route_hint,
        "source": "cli",
        "agent_name": agent_name,
        "max_documents": max_documents,
        "output_format": "json" if json_output else "markdown",
    }
    body = _post_json("/api/context/prepare", payload)
    if body.get("trace_id"):
        _save_state(
            trace_id=body["trace_id"],
            session_id=session,
            project=body.get("project"),
            area=body.get("area"),
            reset_path=True,
        )
    if json_output:
        typer.echo(json.dumps(body, ensure_ascii=False, indent=2))
    else:
        typer.echo(body["markdown"])


@app.command()
def read(
    document_id: Annotated[str, typer.Argument(help="Document ID from the context index.")],
    session: Annotated[
        str | None,
        typer.Option("--session", help="Stable AI conversation/session ID for trace continuity."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print JSON instead of Markdown."),
    ] = False,
) -> None:
    params: dict[str, Any] = {"source": "cli"}
    state = _load_state(session)
    trace_id = state.get("trace_id")
    if trace_id:
        params["trace_id"] = trace_id
    parent_document_id = state.get("last_document_id")
    if parent_document_id and parent_document_id != document_id:
        params["parent_document_id"] = parent_document_id
    depth = _next_depth(state, has_parent="parent_document_id" in params)
    params["depth"] = depth

    body = _get_json(
        f"/api/documents/{document_id}",
        params,
    )
    if body.get("trace_id"):
        _save_state(
            trace_id=body["trace_id"],
            session_id=session,
            last_document_id=document_id,
            depth=depth,
        )
    if json_output:
        typer.echo(json.dumps(body, ensure_ascii=False, indent=2))
    else:
        typer.echo(f"# {body['title']}\n")
        typer.echo(body["content_markdown"])


@app.command()
def reset(
    session: Annotated[
        str | None,
        typer.Option("--session", help="Stable AI conversation/session ID to reset."),
    ] = None,
) -> None:
    """Clear the local ctx trace session."""
    path = _state_path(session)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise typer.BadParameter(f"Failed to reset ctx state: {exc}") from exc
    typer.echo("Reset ctx session")


@app.command()
def trace(
    trace_id: Annotated[str, typer.Argument(help="Trace ID recorded by Context Router.")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print JSON instead of a human-readable summary."),
    ] = False,
) -> None:
    body = _get_json(f"/api/traces/{trace_id}", {})
    if json_output:
        typer.echo(json.dumps(body, ensure_ascii=False, indent=2))
        return

    project = body.get("project", {})
    typer.echo(f"Trace {body['id']}")
    typer.echo(f"Project: {project.get('slug', 'unknown')}")
    if body.get("area"):
        typer.echo(f"Area: {body['area']}")
    if body.get("source"):
        typer.echo(f"Source: {body['source']}")
    typer.echo(f"Task: {body['task']}\n")

    typer.echo("Returned documents:")
    for hit in body.get("retrieval_hits", []):
        feedback = f" [{hit['feedback']}]" if hit.get("feedback") else ""
        typer.echo(
            f"{hit['rank']}. {hit['document_id']} - {hit['document_title']} "
            f"(score {hit['score']}){feedback}"
        )
        typer.echo(f"   {hit['reason']}")

    read_events = [event for event in body.get("events", []) if event.get("event_type") == "read"]
    if read_events:
        typer.echo("\nRead events:")
        for event in read_events:
            payload = event.get("payload", {})
            source = payload.get("source") or "unknown source"
            parent = payload.get("parent_document_id")
            parent_part = f" <- {parent}" if parent else ""
            typer.echo(f"- {payload.get('document_id')}{parent_part} ({source})")


def _next_depth(state: dict[str, Any], *, has_parent: bool) -> int:
    if not has_parent:
        return 1
    try:
        return int(state.get("depth") or 1) + 1
    except (TypeError, ValueError):
        return 2
