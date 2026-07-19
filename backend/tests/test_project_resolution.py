import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from context_router.db.models import Base, Project
from context_router.services.project_resolution import (
    ProjectResolutionError,
    resolve_project,
)


def test_resolve_project_prefers_longest_root_path() -> None:
    with _session() as session:
        workspace = Project(slug="workspace", name="Workspace", root_path="/repo")
        app = Project(slug="app", name="App", root_path="/repo/apps/app")
        session.add_all([workspace, app])
        session.commit()

        resolved = resolve_project(
            session,
            cwd="/repo/apps/app/src",
            project_slug=None,
        )

        assert resolved.slug == "app"


def test_resolve_project_uses_explicit_slug() -> None:
    with _session() as session:
        session.add_all(
            [
                Project(slug="workspace", name="Workspace", root_path="/repo"),
                Project(slug="other", name="Other", root_path="/other"),
            ]
        )
        session.commit()

        resolved = resolve_project(
            session,
            cwd="/repo/src",
            project_slug="other",
        )

        assert resolved.slug == "other"


def test_resolve_project_rejects_unknown_cwd() -> None:
    with _session() as session:
        session.add(Project(slug="app", name="App", root_path="/repo/app"))
        session.commit()

        with pytest.raises(ProjectResolutionError, match="No registered project"):
            resolve_project(session, cwd="/other/repo", project_slug=None)


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
