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


@app.command()
def prepare(
    project: Annotated[str, typer.Option("--project", help="Project slug.")],
    task: Annotated[str, typer.Option("--task", help="Task text from the user.")],
    cwd: Annotated[str | None, typer.Option("--cwd", help="Current repository path.")] = None,
    max_documents: Annotated[int, typer.Option("--max-documents", min=1, max=20)] = 5,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print JSON instead of Markdown."),
    ] = False,
) -> None:
    payload = {
        "project": project,
        "task": task,
        "cwd": cwd,
        "max_documents": max_documents,
        "output_format": "json" if json_output else "markdown",
    }
    body = _post_json("/api/context/prepare", payload)
    if json_output:
        typer.echo(json.dumps(body, ensure_ascii=False, indent=2))
    else:
        typer.echo(body["markdown"])


@app.command()
def read(
    document_id: Annotated[str, typer.Argument(help="Document ID returned by ctx prepare.")],
    trace: Annotated[str, typer.Option("--trace", help="Trace ID returned by ctx prepare.")],
    reason: Annotated[str, typer.Option("--reason", help="Why this full document is needed.")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print JSON instead of Markdown."),
    ] = False,
) -> None:
    body = _get_json(
        f"/api/documents/{document_id}",
        {
            "trace_id": trace,
            "reason": reason,
        },
    )
    if json_output:
        typer.echo(json.dumps(body, ensure_ascii=False, indent=2))
    else:
        typer.echo(f"# {body['title']}\n")
        typer.echo(body["content_markdown"])


@app.command()
def trace(
    trace_id: Annotated[str, typer.Argument(help="Trace ID returned by ctx prepare.")],
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
            typer.echo(f"- {payload.get('document_id')}: {payload.get('reason')}")
