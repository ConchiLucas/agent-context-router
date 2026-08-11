from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_router.api.system_guides import router
from context_router.config import Settings
from context_router.middleware.browser_read_only import BrowserReadOnlyMiddleware
from context_router.repositories.document_read_repository import DocumentReadItemWrite
from context_router.repositories.system_guide_repository import InMemorySystemGuideRepository
from context_router.schemas.context import ContextDocumentReadRequest
from context_router.schemas.system_guides import SystemGuideWrite
from context_router.services.context_document_read import ContextDocumentReadService
from context_router.services.context_preparation import ContextPreparationService
from context_router.services.project_registry import ProjectRegistry
from context_router.services.system_guides import SystemGuideService


def guide_payload(
    key: str = "workspace-directory-access",
    *,
    include_in_prepare: bool = True,
    sort_order: int = 10,
) -> SystemGuideWrite:
    return SystemGuideWrite(
        guide_key=key,
        include_in_prepare=include_in_prepare,
        sort_order=sort_order,
        document={
            "schema_version": 1,
            "key": key,
            "title": "工作空间目录使用规则",
            "summary": "说明主目录与文档阅读目录的使用边界。",
            "sections": [{"title": "主目录", "rules": ["可以使用数据库和部署工具"]}],
        },
    )


def test_system_guide_crud_has_no_enabled_state() -> None:
    service = SystemGuideService(InMemorySystemGuideRepository())

    created = service.create_guide(guide_payload())
    assert created.document_id == "system-guide:workspace-directory-access"
    assert created.include_in_prepare is True
    assert "enabled" not in created.model_dump()

    updated_payload = guide_payload(include_in_prepare=False, sort_order=20)
    updated_payload.document["title"] = "更新后的使用规则"
    updated = service.update_guide(created.id, updated_payload)
    assert updated.title == "更新后的使用规则"
    assert updated.include_in_prepare is False

    service.delete_guide(created.id)
    assert service.list_guides() == []


def test_browser_can_only_update_existing_system_guide_content() -> None:
    service = SystemGuideService(InMemorySystemGuideRepository())
    existing = service.create_guide(guide_payload())
    app = FastAPI()
    app.state.system_guide_service = service
    app.add_middleware(BrowserReadOnlyMiddleware, api_prefix="/api")
    app.include_router(router, prefix="/api")
    headers = {"Origin": "http://127.0.0.1:49175"}

    with TestClient(app) as client:
        created = client.post(
            "/api/system-guides",
            headers=headers,
            json=guide_payload().model_dump(),
        )
        assert created.status_code == 405

        updated_document = dict(guide_payload(include_in_prepare=False).document)
        updated_document["summary"] = "已经更新"
        updated = client.put(
            f"/api/system-guides/{existing.id}/content",
            headers=headers,
            json={"document": updated_document},
        )
        assert updated.status_code == 200
        assert updated.json()["summary"] == "已经更新"
        assert updated.json()["include_in_prepare"] is True

        full_update = client.put(
            f"/api/system-guides/{existing.id}",
            headers=headers,
            json=guide_payload(include_in_prepare=False).model_dump(),
        )
        assert full_update.status_code == 405

        deleted = client.delete(f"/api/system-guides/{existing.id}", headers=headers)
        assert deleted.status_code == 405


class TaskStore:
    def __init__(self) -> None:
        self.task: SimpleNamespace | None = None

    def create_workspace_task(self, **values: object) -> int:
        self.task = SimpleNamespace(
            id=51,
            scope="workspace",
            project_id=None,
            project_key=None,
            created_at=datetime.now(UTC),
            **values,
        )
        return 51

    def get_task(self, task_id: int) -> SimpleNamespace:
        assert task_id == 51 and self.task is not None
        return self.task


class ReadStore:
    def __init__(self) -> None:
        self.items: list[DocumentReadItemWrite] = []

    def create_read_call(
        self,
        *,
        task_id: int,
        items: list[DocumentReadItemWrite],
        tool_call_id: int | None = None,
    ) -> int:
        assert task_id == 51
        assert tool_call_id is None
        self.items = items
        return 81


def test_prepare_returns_guide_catalog_and_read_supports_system_document(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace" / "AGENTS.md"
    root.parent.mkdir()
    root.write_text("# 工作空间入口\n", encoding="utf-8")
    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        )
    )
    registry.add_project(name="测试项目", agents_path=str(root))
    tasks = TaskStore()
    guides = SystemGuideService(InMemorySystemGuideRepository())
    guide = guides.create_guide(guide_payload())

    prepared = ContextPreparationService(
        registry,
        tasks,  # type: ignore[arg-type]
    ).prepare(task="检查使用规则", cwd=str(root.parent))

    assert prepared.access == [
        "documents",
        "database",
        "environment",
        "middleware",
        "runtime",
    ]
    assert "system_guides" not in prepared.model_dump(exclude_none=True)

    read_store = ReadStore()
    result = ContextDocumentReadService(
        registry,
        tasks,  # type: ignore[arg-type]
        read_store,
        guides,
    ).read(
        task_id=prepared.task_id,
        requests=[ContextDocumentReadRequest(document_id=guide.document_id)],
    )

    assert result.documents[0].path == "system-guides/workspace-directory-access.json"
    assert '"title": "工作空间目录使用规则"' in (result.documents[0].content or "")
    assert read_store.items[0].status == "ok"
