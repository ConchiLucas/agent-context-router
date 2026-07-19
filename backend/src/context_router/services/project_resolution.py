from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from context_router.config import settings
from context_router.db.models import Project


class ProjectResolutionError(ValueError):
    pass


def resolve_project(
    session: Session,
    *,
    cwd: str,
    project_slug: str | None,
) -> Project:
    if project_slug:
        project = session.scalar(select(Project).where(Project.slug == project_slug))
        if project is None:
            raise ProjectResolutionError(f"Project not found: {project_slug}")
        return project

    normalized_cwd = _normalized_host_path(cwd)
    projects = session.scalars(select(Project).where(Project.root_path.is_not(None))).all()
    matches = [
        project
        for project in projects
        if project.root_path
        and _is_within(
            normalized_cwd,
            _normalized_host_path(project.root_path),
        )
    ]
    if not matches:
        raise ProjectResolutionError(f"No registered project matches cwd: {cwd}")

    return max(
        matches,
        key=lambda project: len(_normalized_host_path(project.root_path or "").parts),
    )


def _normalized_host_path(value: str) -> Path:
    path = Path(value).expanduser().resolve(strict=False)
    container_root = settings.workspace_container_root
    host_root = settings.workspace_host_root
    if not container_root or not host_root:
        return path

    try:
        relative = path.relative_to(Path(container_root).expanduser().resolve(strict=False))
    except ValueError:
        return path
    return Path(host_root).expanduser().resolve(strict=False) / relative


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
