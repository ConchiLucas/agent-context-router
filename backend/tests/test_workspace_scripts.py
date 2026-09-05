from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from context_router.config import settings
from context_router.db.models import Base, Project
from context_router.db.session import get_session
from context_router.main import create_app
from context_router.services.workspace_scripts import (
    PANZHIHUA_SLUG,
    import_panzhihua_scripts_once,
    import_workspace_scripts_once,
)


def _client(session_factory: sessionmaker[Session]) -> TestClient:
    def override_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def _memory_session() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    return TestingSession


def _write_panzhihua_scripts(root: Path) -> Path:
    script_dir = root / "script"
    (script_dir / "ai").mkdir(parents=True)
    (script_dir / "start.sh").write_text(
        "#!/usr/bin/env bash\n# 启动攀枝花本地栈\n# 工作空间默认开机脚本\necho start\n",
        encoding="utf-8",
    )
    (script_dir / "ai" / "inspect-schema.sh").write_text(
        "#!/usr/bin/env bash\n# 查看当前库表\necho inspect\n",
        encoding="utf-8",
    )
    (script_dir / "notes.bin").write_bytes(b"\x00\x01\x02")
    return script_dir


def test_import_maps_script_dir_once_and_classifies_kinds(tmp_path) -> None:
    TestingSession = _memory_session()
    script_dir = _write_panzhihua_scripts(tmp_path)

    with TestingSession() as session:
        project = Project(
            slug=PANZHIHUA_SLUG,
            name="攀枝花开发工作空间",
            root_path=str(tmp_path),
        )
        session.add(project)
        session.flush()
        first = import_workspace_scripts_once(session, project=project, script_dir=script_dir)
        second = import_workspace_scripts_once(session, project=project, script_dir=script_dir)
        session.commit()

        assert first.imported_count == 2
        assert first.skipped_existing is False
        assert second.skipped_existing is True
        assert second.imported_count == 0

    client = _client(TestingSession)
    listing = client.get(f"/api/projects/{PANZHIHUA_SLUG}/scripts")
    assert listing.status_code == 200
    scripts = listing.json()["scripts"]
    assert [item["relative_path"] for item in scripts] == ["ai/inspect-schema.sh", "start.sh"]
    assert scripts[0]["kind"] == "workspace_ai"
    assert scripts[1]["kind"] == "workspace_autostart"
    assert scripts[1]["name"] == "启动攀枝花本地栈"

    detail = client.get(f"/api/projects/{PANZHIHUA_SLUG}/scripts/start")
    assert detail.status_code == 200
    assert "工作空间默认开机脚本" in detail.json()["content"]

    assert client.post(f"/api/projects/{PANZHIHUA_SLUG}/scripts").status_code == 405
    assert client.put(f"/api/projects/{PANZHIHUA_SLUG}/scripts/start").status_code == 405
    assert client.delete(f"/api/projects/{PANZHIHUA_SLUG}/scripts/start").status_code == 405


def test_project_card_counts_include_imported_scripts(tmp_path) -> None:
    TestingSession = _memory_session()
    script_dir = _write_panzhihua_scripts(tmp_path)

    with TestingSession() as session:
        session.add(
            Project(
                slug=PANZHIHUA_SLUG,
                name="攀枝花开发工作空间",
                root_path=str(tmp_path),
            )
        )
        session.commit()
        import_panzhihua_scripts_once(session, script_dir=script_dir)
        session.commit()

    client = _client(TestingSession)
    response = client.get("/api/projects")
    assert response.status_code == 200
    project = response.json()["projects"][0]
    assert project["slug"] == PANZHIHUA_SLUG
    assert project["script_count"] == 2
    assert project["autostart_script_count"] == 1


def test_missing_script_dir_does_not_create_rows(tmp_path, monkeypatch) -> None:
    TestingSession = _memory_session()
    monkeypatch.setattr(settings, "scripts_snapshot_root", str(tmp_path / "missing-snapshot"))
    monkeypatch.setattr(settings, "workspace_host_root", None)
    monkeypatch.setattr(settings, "workspace_container_root", None)

    with TestingSession() as session:
        session.add(
            Project(
                slug=PANZHIHUA_SLUG,
                name="攀枝花开发工作空间",
                root_path=str(tmp_path / "no-script-dir"),
            )
        )
        session.commit()
        result = import_panzhihua_scripts_once(session)
        session.commit()
        assert result.imported_count == 0
        assert result.source_dir is None
