from __future__ import annotations

from pathlib import Path, PurePosixPath


class WorkspacePathError(ValueError):
    pass


def normalize_workspace_root_path(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise WorkspacePathError("工作空间根目录不能为空")
    path = Path(normalized).expanduser()
    if not path.is_absolute():
        raise WorkspacePathError("工作空间根目录必须是绝对路径")
    return str(path)


def normalize_project_relative_path(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise WorkspacePathError("项目相对路径不能为空")
    if "\\" in normalized:
        raise WorkspacePathError("项目相对路径必须使用 / 分隔")
    if normalized.startswith("~"):
        raise WorkspacePathError("项目相对路径不能使用 ~")

    path = PurePosixPath(normalized)
    if path.is_absolute():
        raise WorkspacePathError("项目路径必须相对于工作空间")
    if ".." in path.parts:
        raise WorkspacePathError("项目相对路径不能包含 ..")

    rendered = path.as_posix()
    return "." if rendered in {"", "."} else rendered.removeprefix("./")


def derive_agents_path(workspace_root_path: str, relative_path: str) -> str:
    root = Path(normalize_workspace_root_path(workspace_root_path))
    normalized_relative = normalize_project_relative_path(relative_path)
    project_root = (
        root if normalized_relative == "." else root.joinpath(*normalized_relative.split("/"))
    )
    return str(project_root / "AGENTS.md")


def resolve_project_root(workspace_root: Path, relative_path: str) -> Path:
    normalized_relative = normalize_project_relative_path(relative_path)
    resolved_workspace = workspace_root.resolve()
    candidate = (
        resolved_workspace
        if normalized_relative == "."
        else resolved_workspace.joinpath(*normalized_relative.split("/")).resolve()
    )
    try:
        candidate.relative_to(resolved_workspace)
    except ValueError as exc:
        raise WorkspacePathError("项目路径不能越出工作空间") from exc
    return candidate
