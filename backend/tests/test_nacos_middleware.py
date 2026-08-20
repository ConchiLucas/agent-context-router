from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from context_router.repositories.mcp_environment_default_repository import (
    InMemoryMcpEnvironmentDefaultRepository,
)
from context_router.repositories.nacos_profile_repository import (
    InMemoryNacosProfileRepository,
    NacosProfileWrite,
)
from context_router.repositories.task_repository import TaskRecord
from context_router.services.nacos_middleware import (
    MiddlewareContextError,
    MiddlewareContextService,
    NacosConfigDocument,
)


class StaticTaskRepository:
    def __init__(self, task: TaskRecord) -> None:
        self.task = task

    def get_task(self, task_id: int) -> TaskRecord:
        assert task_id == self.task.id
        return self.task


class StaticRegistry:
    def __init__(self, workspace_id: str, *, access_mode: str = "full") -> None:
        self.workspace = SimpleNamespace(
            id=workspace_id,
            key="workspace-key",
            access_mode=access_mode,
        )

    def get_workspace_snapshot_for_task(self, **_: object) -> object:
        return self.workspace

    def find_workspace_for_cwd(self, _cwd: str) -> object:
        return self.workspace


class RecordingDatabaseAccess:
    def __init__(self, environment: str | None) -> None:
        self.environment = environment
        self.calls: list[dict[str, object]] = []

    def validate_task_environment(self, workspace_id: str, **values: object) -> str | None:
        self.calls.append({"workspace_id": workspace_id, **values})
        return self.environment


class StaticNacosReader:
    def __init__(self, documents: dict[tuple[str, str], NacosConfigDocument]) -> None:
        self.documents = documents
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def get_config(self, *, data_id: str, group: str) -> NacosConfigDocument:
        self.calls.append((data_id, group))
        document = self.documents.get((data_id, group))
        if document is None:
            raise MiddlewareContextError("nacos_config_not_found", "配置不存在")
        return document

    def close(self) -> None:
        self.closed = True


def _task(*, environment: str | None, explicit: bool = True) -> TaskRecord:
    return TaskRecord(
        id=41,
        project_id=None,
        project_key="workspace-key",
        project_name="Workspace",
        task="排查中间件",
        cwd="/workspace/project",
        agent_name="codex",
        created_at=datetime.now(UTC),
        scope="workspace",
        workspace_id="workspace-1",
        workspace_key="workspace-key",
        workspace_name="Workspace",
        database_environment=environment,
        database_environment_revision=7 if environment else None,
        database_environment_selection=(
            "task_explicit"
            if environment and explicit
            else "workspace_default"
            if environment
            else None
        ),
    )


def _profile(
    repository: InMemoryNacosProfileRepository,
    *,
    profile_key: str,
) -> None:
    repository.upsert_profile(
        NacosProfileWrite(
            workspace_id="workspace-1",
            profile_key=profile_key,  # type: ignore[arg-type]
            base_url="http://host.docker.internal:9102",
            namespace_id=f"{profile_key}-namespace",
            username="nacos",
            password="profile-password-must-not-escape",
            request_timeout_ms=5000,
            components=[
                {
                    "id": "redis-main",
                    "type": "redis",
                    "sources": [{"data_id": "c12-common.yaml", "group": "DEFAULT_GROUP"}],
                    "fields": {
                        "host": {"paths": ["spring.data.redis.host"], "secret": False},
                        "port": {"paths": ["spring.data.redis.port"], "secret": False},
                        "password": {
                            "paths": ["spring.data.redis.password"],
                            "secret": True,
                        },
                    },
                },
                {
                    "id": "rocketmq",
                    "type": "rocketmq",
                    "sources": [{"data_id": "c12-common.yaml", "group": "DEFAULT_GROUP"}],
                    "fields": {
                        "nameServer": {
                            "paths": ["chinaservices.rocketmq.name-server"],
                            "secret": False,
                        }
                    },
                },
            ],
        )
    )


def _reader() -> StaticNacosReader:
    return StaticNacosReader(
        {
            ("c12-common.yaml", "DEFAULT_GROUP"): NacosConfigDocument(
                data_id="c12-common.yaml",
                group="DEFAULT_GROUP",
                config_type="yaml",
                md5="abc123",
                modified_at="2026-08-11T10:00:00+08:00",
                content="""
spring:
  data:
    redis:
      host: ${REDIS_HOST:redis.test.local}
      port: 6379
      password: redis-secret
chinaservices:
  rocketmq:
    name-server: mq.test.local:9876
""",
            )
        }
    )


def test_task_environment_selects_exact_profile_and_redacts_secrets() -> None:
    profiles = InMemoryNacosProfileRepository()
    _profile(profiles, profile_key="test")
    reader = _reader()
    database_access = RecordingDatabaseAccess("test")
    service = MiddlewareContextService(
        registry=StaticRegistry("workspace-1"),  # type: ignore[arg-type]
        task_repository=StaticTaskRepository(_task(environment="test")),
        profile_repository=profiles,
        database_access_service=database_access,  # type: ignore[arg-type]
        reader_factory=lambda _profile: reader,
    )

    result = service.read(
        task_id=41,
        components=["redis-main", "rocketmq"],
        reveal_secrets=False,
    )

    assert result.profile_key == "test"
    assert result.environment == "test"
    assert result.secrets_revealed is False
    assert result.components[0].properties == {
        "host": "redis.test.local",
        "port": 6379,
        "password": "***REDACTED***",
    }
    assert result.components[1].properties == {"nameServer": "mq.test.local:9876"}
    assert reader.calls == [("c12-common.yaml", "DEFAULT_GROUP")]
    assert reader.closed is True
    assert "redis-secret" not in repr(result)
    assert "profile-password-must-not-escape" not in repr(result)
    assert database_access.calls[0]["task_environment"] == "test"


def test_explicit_reveal_returns_secret_and_single_environment_uses_local_profile() -> None:
    profiles = InMemoryNacosProfileRepository()
    _profile(profiles, profile_key="local")
    reader = _reader()
    service = MiddlewareContextService(
        registry=StaticRegistry("workspace-1"),  # type: ignore[arg-type]
        task_repository=StaticTaskRepository(_task(environment=None)),
        profile_repository=profiles,
        database_access_service=RecordingDatabaseAccess(None),  # type: ignore[arg-type]
        reader_factory=lambda _profile: reader,
    )

    result = service.read(task_id=41, components=["redis-main"], reveal_secrets=True)

    assert result.profile_key == "local"
    assert result.environment == "local"
    assert result.components[0].properties["password"] == "redis-secret"


def test_omitted_environment_inherits_the_task_environment() -> None:
    profiles = InMemoryNacosProfileRepository()
    _profile(profiles, profile_key="uat")
    reader = _reader()
    database_access = RecordingDatabaseAccess("uat")
    service = MiddlewareContextService(
        registry=StaticRegistry("workspace-1"),  # type: ignore[arg-type]
        task_repository=StaticTaskRepository(_task(environment="uat", explicit=False)),
        profile_repository=profiles,
        database_access_service=database_access,  # type: ignore[arg-type]
        reader_factory=lambda _profile: reader,
    )

    result = service.read(task_id=41, components=["redis-main"], reveal_secrets=False)

    assert result.profile_key == "uat"
    assert result.environment == "uat"
    assert len(database_access.calls) == 1


def test_removed_middleware_tool_default_does_not_override_local_task_default() -> None:
    profiles = InMemoryNacosProfileRepository()
    _profile(profiles, profile_key="local")
    defaults = InMemoryMcpEnvironmentDefaultRepository()
    defaults.upsert_default(
        workspace_id="workspace-1",
        tool_name="read_middleware_context",
        environment="test",
    )
    reader = _reader()
    service = MiddlewareContextService(
        registry=StaticRegistry("workspace-1"),  # type: ignore[arg-type]
        task_repository=StaticTaskRepository(_task(environment=None)),
        profile_repository=profiles,
        database_access_service=RecordingDatabaseAccess(None),  # type: ignore[arg-type]
        mcp_environment_defaults=defaults,
        reader_factory=lambda _profile: reader,
    )

    result = service.read(task_id=41, components=["redis-main"], reveal_secrets=False)

    assert result.profile_key == "local"
    assert result.environment == "local"


def test_empty_workspace_defaults_use_registered_local_middleware_default() -> None:
    profiles = InMemoryNacosProfileRepository()
    _profile(profiles, profile_key="test")
    service = MiddlewareContextService(
        registry=StaticRegistry("workspace-1"),  # type: ignore[arg-type]
        task_repository=StaticTaskRepository(_task(environment="test")),
        profile_repository=profiles,
        database_access_service=RecordingDatabaseAccess("test"),  # type: ignore[arg-type]
        mcp_environment_defaults=InMemoryMcpEnvironmentDefaultRepository(),
        reader_factory=lambda _profile: _reader(),
    )

    result = service.read(task_id=41, components=["redis-main"], reveal_secrets=False)

    assert result.profile_key == "test"
    assert result.environment == "test"


def test_unknown_component_and_document_reader_are_rejected_before_nacos_access() -> None:
    profiles = InMemoryNacosProfileRepository()
    _profile(profiles, profile_key="local")
    reader = _reader()
    service = MiddlewareContextService(
        registry=StaticRegistry("workspace-1", access_mode="documents_only"),  # type: ignore[arg-type]
        task_repository=StaticTaskRepository(_task(environment=None)),
        profile_repository=profiles,
        database_access_service=RecordingDatabaseAccess(None),  # type: ignore[arg-type]
        reader_factory=lambda _profile: reader,
    )

    with pytest.raises(MiddlewareContextError, match="只能读取文档") as failed:
        service.read(task_id=41, components=["unknown"], reveal_secrets=True)

    assert failed.value.code == "documents_only"
    assert reader.calls == []
