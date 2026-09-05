from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from context_router.config import settings
from context_router.db.models import Project, WorkspaceScript

PANZHIHUA_SLUG = "panzhihua-dev-workforce"
PANZHIHUA_NAME = "攀枝花开发工作空间"
PANZHIHUA_ROOT_PATH = "/Users/conchi/workforce/company_workforce/panzhihua_dev_workforce"
SCRIPT_DIR_NAME = "script"
TEXT_SUFFIXES = {
    "",
    ".sh",
    ".bash",
    ".zsh",
    ".py",
    ".js",
    ".ts",
    ".sql",
    ".md",
    ".yml",
    ".yaml",
    ".toml",
    ".json",
    ".env",
    ".conf",
    ".ini",
}
SKIP_DIR_NAMES = {".git", ".svn", "node_modules", "__pycache__", ".venv", "dist", "build"}
MAX_SCRIPT_BYTES = 1_000_000


@dataclass(frozen=True)
class ScriptImportResult:
    project_slug: str
    imported_count: int
    skipped_existing: bool
    source_dir: str | None


def list_workspace_scripts(session: Session, *, project: Project) -> list[WorkspaceScript]:
    return list(
        session.scalars(
            select(WorkspaceScript)
            .where(WorkspaceScript.project_id == project.id)
            .order_by(WorkspaceScript.relative_path)
        ).all()
    )


def get_workspace_script(
    session: Session,
    *,
    project: Project,
    script_slug: str,
) -> WorkspaceScript | None:
    return session.scalar(
        select(WorkspaceScript).where(
            WorkspaceScript.project_id == project.id,
            WorkspaceScript.slug == script_slug,
        )
    )


def ensure_panzhihua_workspace(session: Session) -> Project:
    project = session.scalar(select(Project).where(Project.slug == PANZHIHUA_SLUG))
    if project is not None:
        if not project.root_path:
            project.root_path = PANZHIHUA_ROOT_PATH
        return project

    project = Project(
        slug=PANZHIHUA_SLUG,
        name=PANZHIHUA_NAME,
        root_path=PANZHIHUA_ROOT_PATH,
        description="公司攀枝花开发工作空间。脚本以数据库为编辑源，界面只读。",
    )
    session.add(project)
    session.flush()
    return project


def import_panzhihua_scripts_once(
    session: Session,
    *,
    script_dir: Path | None = None,
) -> ScriptImportResult:
    project = session.scalar(select(Project).where(Project.slug == PANZHIHUA_SLUG))
    if project is None:
        return ScriptImportResult(
            project_slug=PANZHIHUA_SLUG,
            imported_count=0,
            skipped_existing=False,
            source_dir=None,
        )
    return import_workspace_scripts_once(session, project=project, script_dir=script_dir)


def import_workspace_scripts_once(
    session: Session,
    *,
    project: Project,
    script_dir: Path | None = None,
) -> ScriptImportResult:
    existing = session.scalar(
        select(WorkspaceScript.id).where(WorkspaceScript.project_id == project.id).limit(1)
    )
    if existing is not None:
        return ScriptImportResult(
            project_slug=project.slug,
            imported_count=0,
            skipped_existing=True,
            source_dir=None,
        )

    resolved_dir = script_dir or resolve_script_dir(project)
    if resolved_dir is None:
        return ScriptImportResult(
            project_slug=project.slug,
            imported_count=0,
            skipped_existing=False,
            source_dir=None,
        )

    imported_at = datetime.now(UTC)
    imported_count = 0
    used_slugs: set[str] = set()
    for path in _iter_script_files(resolved_dir):
        relative_path = path.relative_to(resolved_dir).as_posix()
        content = path.read_text(encoding="utf-8")
        slug = _unique_slug(_slug_from_relative_path(relative_path), used_slugs)
        used_slugs.add(slug)
        session.add(
            WorkspaceScript(
                project_id=project.id,
                slug=slug,
                name=_name_from_file(path, content),
                description=_description_from_content(content),
                kind=_kind_from_relative_path(relative_path),
                relative_path=relative_path,
                content=content,
                imported_at=imported_at,
            )
        )
        imported_count += 1

    session.flush()
    return ScriptImportResult(
        project_slug=project.slug,
        imported_count=imported_count,
        skipped_existing=False,
        source_dir=str(resolved_dir),
    )


def resolve_script_dir(project: Project) -> Path | None:
    candidates: list[Path] = []
    snapshot_root = settings.scripts_snapshot_root
    if snapshot_root:
        candidates.append(Path(snapshot_root).expanduser() / project.slug / SCRIPT_DIR_NAME)
    else:
        candidates.append(_default_snapshot_dir(project.slug))

    if project.root_path:
        host_script_dir = Path(project.root_path).expanduser() / SCRIPT_DIR_NAME
        candidates.append(host_script_dir)
        mapped = _container_script_dir(project.root_path)
        if mapped is not None:
            candidates.append(mapped)

    for candidate in candidates:
        if _is_usable_script_dir(candidate):
            return candidate.resolve()
    return None


def _default_snapshot_dir(project_slug: str) -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "script-sources"
        / project_slug
        / SCRIPT_DIR_NAME
    )


def _container_script_dir(root_path: str) -> Path | None:
    host_root = settings.workspace_host_root
    container_root = settings.workspace_container_root
    if not host_root or not container_root:
        return None
    try:
        relative = Path(root_path).expanduser().relative_to(Path(host_root).expanduser())
    except ValueError:
        return None
    return Path(container_root).expanduser() / relative / SCRIPT_DIR_NAME


def _is_usable_script_dir(path: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return False
    return resolved.is_dir() and not resolved.is_symlink()


def _iter_script_files(script_dir: Path):
    for path in sorted(script_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in SKIP_DIR_NAMES or part.startswith(".") for part in path.relative_to(script_dir).parts[:-1]):
            continue
        if path.name.startswith("."):
            continue
        if path.stat().st_size > MAX_SCRIPT_BYTES:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Makefile", "Dockerfile"}:
            continue
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        yield path


def _slug_from_relative_path(relative_path: str) -> str:
    stem = Path(relative_path).with_suffix("").as_posix()
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return slug or "script"


def _unique_slug(slug: str, used: set[str]) -> str:
    if slug not in used:
        return slug
    index = 2
    while f"{slug}-{index}" in used:
        index += 1
    return f"{slug}-{index}"


def _name_from_file(path: Path, content: str) -> str:
    for line in content.splitlines()[:8]:
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("#!"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return path.name


def _description_from_content(content: str) -> str:
    comments: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            if comments:
                break
            continue
        if stripped.startswith("#!"):
            continue
        if stripped.startswith("#"):
            comments.append(stripped.lstrip("#").strip())
            continue
        break
    return " ".join(part for part in comments if part)


def _kind_from_relative_path(relative_path: str) -> str:
    normalized = relative_path.lower()
    autostart_markers = ("autostart", "boot", "开机", "must-start", "default-start")
    if any(marker in normalized for marker in autostart_markers):
        return "workspace_autostart"
    name = Path(normalized).name
    if name in {"start.sh", "start-stack.sh", "up.sh"}:
        return "workspace_autostart"
    return "workspace_ai"
