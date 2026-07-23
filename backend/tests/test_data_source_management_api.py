from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from context_router.config import Settings
from context_router.database.errors import DatabaseConnectorError
from context_router.database.models import ConnectorCapabilities
from context_router.database.registry import ConnectorRegistry
from context_router.main import create_app
from context_router.repositories.data_source_repository import InMemoryDataSourceRepository
from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.services.database_discovery import DiscoveredDatabase


def test_data_source_database_and_project_link_crud(tmp_path: Path, monkeypatch) -> None:
    agents_path = tmp_path / "project" / "AGENTS.md"
    agents_path.parent.mkdir(parents=True)
    agents_path.write_text("# Project", encoding="utf-8")
    app = create_app(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        ),
        project_repository=InMemoryProjectRepository(),
        data_source_repository=InMemoryDataSourceRepository(),
    )
    invalidated_sources: list[str] = []
    monkeypatch.setattr(
        app.state.connector_manager,
        "invalidate_source",
        invalidated_sources.append,
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "订单项目", "agents_path": str(agents_path)},
        ).json()
        created_source = client.post(
            "/api/data-sources",
            json={
                "name": "本地 MySQL",
                "engine": "mysql",
                "description": "开发连接",
                "connection_config": {
                    "host": "127.0.0.1",
                    "port": 3306,
                    "username": "root",
                    "password": "private",
                },
                "enabled": True,
            },
        )
        source = created_source.json()
        revealed_password = client.post(f"/api/data-sources/{source['id']}/reveal-password")
        created_database = client.post(
            f"/api/data-sources/{source['id']}/databases",
            json={
                "remote_name": "orders",
                "display_name": "订单库",
                "namespace_type": "database",
                "available": True,
                "system_database": False,
                "metadata": {},
            },
        )
        database = created_database.json()
        created_link = client.post(
            f"/api/data-sources/databases/{database['id']}/projects",
            json={
                "project_id": project["id"],
                "alias": "订单主库",
                "purpose": "查询订单",
                "enabled": True,
                "readonly": True,
                "allowed_schemas": [],
                "max_rows": 1000,
                "max_result_bytes": 2_000_000,
                "query_timeout_ms": 15_000,
            },
        )
        listed_sources = client.get("/api/data-sources")
        listed_databases = client.get(f"/api/data-sources/{source['id']}/databases")
        listed_project_databases = client.get(f"/api/projects/{project['id']}/databases")
        deleted_link = client.delete(
            f"/api/data-sources/databases/{database['id']}/projects/{created_link.json()['id']}"
        )
        deleted_database = client.delete(
            f"/api/data-sources/{source['id']}/databases/{database['id']}"
        )
        deleted_source = client.delete(f"/api/data-sources/{source['id']}")

    assert created_source.status_code == 201
    assert source["category"] == "本机电脑"
    assert "password" not in source["connection_config"]
    assert revealed_password.status_code == 200
    assert revealed_password.json() == {"password": "private"}
    assert revealed_password.headers["cache-control"] == "no-store"
    assert created_database.status_code == 201
    assert created_link.status_code == 201
    assert created_link.json()["project_name"] == "订单项目"
    assert created_link.json()["mcp_alias"] == "orders"
    assert listed_sources.json()[0]["database_count"] == 1
    assert listed_sources.json()[0]["project_count"] == 1
    assert listed_databases.json()[0]["project_count"] == 1
    assert listed_project_databases.json()[0]["database_name"] == "orders"
    assert deleted_link.status_code == 204
    assert deleted_database.status_code == 204
    assert deleted_source.status_code == 204
    assert invalidated_sources == [source["id"], source["id"]]


def test_updating_source_with_blank_password_preserves_secret(tmp_path: Path) -> None:
    repository = InMemoryDataSourceRepository()
    app = create_app(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        ),
        project_repository=InMemoryProjectRepository(),
        data_source_repository=repository,
    )

    with TestClient(app) as client:
        source = client.post(
            "/api/data-sources",
            json={
                "name": "PG",
                "engine": "postgresql",
                "connection_config": {"host": "localhost", "password": "secret"},
            },
        ).json()
        updated = client.put(
            f"/api/data-sources/{source['id']}",
            json={
                "name": "PG Dev",
                "category": "公司内网服务器",
                "engine": "postgresql",
                "description": "",
                "connection_config": {"host": "127.0.0.1", "password": ""},
                "enabled": True,
            },
        )

    assert updated.status_code == 200
    assert updated.json()["category"] == "公司内网服务器"
    assert repository.get_data_source(source["id"]).connection_config["password"] == "secret"


def test_project_replaces_database_selection_in_one_request(tmp_path: Path) -> None:
    agents_path = tmp_path / "project" / "AGENTS.md"
    agents_path.parent.mkdir(parents=True)
    agents_path.write_text("# Project", encoding="utf-8")
    app = create_app(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        ),
        project_repository=InMemoryProjectRepository(),
        data_source_repository=InMemoryDataSourceRepository(),
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "批量授权项目", "agents_path": str(agents_path)},
        ).json()
        source = client.post(
            "/api/data-sources",
            json={
                "name": "本地 PostgreSQL",
                "category": "本机电脑",
                "engine": "postgresql",
                "connection_config": {"host": "localhost"},
            },
        ).json()
        databases = [
            client.post(
                f"/api/data-sources/{source['id']}/databases",
                json={
                    "remote_name": name,
                    "display_name": name,
                    "namespace_type": "database",
                },
            ).json()
            for name in ("app", "report")
        ]

        initial = client.get(f"/api/projects/{project['id']}/data-source-options")
        selected_one = client.put(
            f"/api/projects/{project['id']}/databases",
            json={"database_ids": [databases[0]["id"]]},
        )
        first_link_id = selected_one.json()["sources"][0]["databases"][0]["link_id"]
        selected_both = client.put(
            f"/api/projects/{project['id']}/databases",
            json={"database_ids": [item["id"] for item in databases]},
        )
        selected_second = client.put(
            f"/api/projects/{project['id']}/databases",
            json={"database_ids": [databases[1]["id"]]},
        )
        links = client.get(f"/api/projects/{project['id']}/databases")
        duplicate = client.put(
            f"/api/projects/{project['id']}/databases",
            json={"database_ids": [databases[1]["id"], databases[1]["id"]]},
        )

    assert initial.status_code == 200
    assert initial.json()["selected_database_count"] == 0
    assert selected_one.status_code == 200
    assert selected_one.json()["selected_database_count"] == 1
    assert selected_both.status_code == 200
    assert selected_both.json()["selected_database_count"] == 2
    assert selected_both.json()["sources"][0]["databases"][0]["link_id"] == first_link_id
    assert selected_second.status_code == 200
    assert selected_second.json()["selected_database_count"] == 1
    assert links.json()[0]["database_name"] == "report"
    assert links.json()[0]["mcp_alias"] == "report"
    assert duplicate.status_code == 400


def test_project_database_mcp_alias_can_be_generated_edited_and_is_unique(
    tmp_path: Path,
) -> None:
    agents_path = tmp_path / "project" / "AGENTS.md"
    agents_path.parent.mkdir(parents=True)
    agents_path.write_text("# Project", encoding="utf-8")
    app = create_app(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        ),
        project_repository=InMemoryProjectRepository(),
        data_source_repository=InMemoryDataSourceRepository(),
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "分析项目", "agents_path": str(agents_path)},
        ).json()
        source = client.post(
            "/api/data-sources",
            json={
                "name": "分析数据库",
                "engine": "postgresql",
                "connection_config": {"host": "localhost"},
            },
        ).json()
        databases = [
            client.post(
                f"/api/data-sources/{source['id']}/databases",
                json={
                    "remote_name": name,
                    "display_name": display_name,
                    "namespace_type": "database",
                },
            ).json()
            for name, display_name in (("events", "事件库"), ("warehouse", "数仓"))
        ]
        generated = client.post(
            f"/api/data-sources/databases/{databases[0]['id']}/projects",
            json={
                "project_id": project["id"],
                "alias": "行为分析",
                "purpose": "查询事件",
            },
        )
        explicit = client.post(
            f"/api/data-sources/databases/{databases[1]['id']}/projects",
            json={
                "project_id": project["id"],
                "alias": "离线数仓",
                "mcp_alias": "warehouse",
                "purpose": "查询数仓",
            },
        )
        conflict = client.put(
            f"/api/data-sources/databases/{databases[1]['id']}/projects/{explicit.json()['id']}",
            json={
                "project_id": project["id"],
                "alias": "离线数仓",
                "mcp_alias": "events",
                "purpose": "查询数仓",
            },
        )
        edited = client.put(
            f"/api/data-sources/databases/{databases[1]['id']}/projects/{explicit.json()['id']}",
            json={
                "project_id": project["id"],
                "alias": "离线数仓",
                "mcp_alias": "offline_warehouse",
                "purpose": "查询数仓",
            },
        )
        patched = client.patch(
            f"/api/projects/{project['id']}/databases/{explicit.json()['id']}/mcp-alias",
            json={"mcp_alias": "warehouse_readonly"},
        )
        swapped = client.put(
            f"/api/projects/{project['id']}/databases",
            json={
                "database_ids": [database["id"] for database in databases],
                "mcp_aliases": {
                    databases[0]["id"]: "warehouse_readonly",
                    databases[1]["id"]: "events",
                },
            },
        )
        duplicate_batch = client.put(
            f"/api/projects/{project['id']}/databases",
            json={
                "database_ids": [database["id"] for database in databases],
                "mcp_aliases": {
                    databases[0]["id"]: "duplicate",
                    databases[1]["id"]: "duplicate",
                },
            },
        )
        after_duplicate = client.get(f"/api/projects/{project['id']}/data-source-options")
        invalid = client.post(
            f"/api/data-sources/databases/{databases[1]['id']}/projects",
            json={
                "project_id": project["id"],
                "mcp_alias": "Bad Alias",
            },
        )

    assert generated.status_code == 201
    assert generated.json()["mcp_alias"] == "events"
    assert explicit.status_code == 201
    assert explicit.json()["mcp_alias"] == "warehouse"
    assert conflict.status_code == 400
    assert conflict.json()["detail"] == "项目内 MCP 数据库别名已存在"
    assert edited.status_code == 200
    assert edited.json()["mcp_alias"] == "offline_warehouse"
    assert patched.status_code == 200
    assert patched.json()["mcp_alias"] == "warehouse_readonly"
    assert swapped.status_code == 200
    swapped_aliases = {
        database["id"]: database["mcp_alias"]
        for source_option in swapped.json()["sources"]
        for database in source_option["databases"]
        if database["selected"]
    }
    assert swapped_aliases == {
        databases[0]["id"]: "warehouse_readonly",
        databases[1]["id"]: "events",
    }
    assert duplicate_batch.status_code == 422
    persisted_aliases = {
        database["id"]: database["mcp_alias"]
        for source_option in after_duplicate.json()["sources"]
        for database in source_option["databases"]
        if database["selected"]
    }
    assert persisted_aliases == swapped_aliases
    assert invalid.status_code == 422


def test_engine_capabilities_and_connection_test_use_registered_connector(
    tmp_path: Path,
) -> None:
    connectors: list[FakeConnectionTestConnector] = []
    registry = ConnectorRegistry()

    def factory(spec):
        connector = FakeConnectionTestConnector(spec.engine)
        connectors.append(connector)
        return connector

    registry.register(
        "mysql",
        factory,
        ConnectorCapabilities(
            discover_databases=True,
            search_tables=True,
            execute_readonly_query=True,
        ),
    )
    app = create_app(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        ),
        project_repository=InMemoryProjectRepository(),
        data_source_repository=InMemoryDataSourceRepository(),
        connector_registry=registry,
    )

    with TestClient(app) as client:
        source = client.post(
            "/api/data-sources",
            json={
                "name": "可测试 MySQL",
                "engine": "mysql",
                "connection_config": {"host": "db.internal", "password": "private"},
            },
        ).json()
        capabilities = client.get("/api/data-source-engines")
        tested = client.post(f"/api/data-sources/{source['id']}/test")

    mysql = next(item for item in capabilities.json() if item["engine"] == "mysql")
    sqlite = next(item for item in capabilities.json() if item["engine"] == "sqlite")
    assert mysql == {
        "engine": "mysql",
        "configurable": True,
        "discoverable": True,
        "searchable": True,
        "queryable": True,
    }
    assert sqlite["configurable"] is True
    assert sqlite["queryable"] is False
    assert tested.status_code == 200
    assert tested.json()["status"] == "passed"
    assert connectors[0].pinged is True
    assert connectors[0].closed is True


def test_connection_test_returns_sanitized_failure_and_closes_connector(
    tmp_path: Path,
) -> None:
    connectors: list[FakeConnectionTestConnector] = []
    registry = ConnectorRegistry()

    def factory(spec):
        connector = FakeConnectionTestConnector(spec.engine, fail=True)
        connectors.append(connector)
        return connector

    registry.register("mysql", factory, ConnectorCapabilities())
    app = create_app(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        ),
        project_repository=InMemoryProjectRepository(),
        data_source_repository=InMemoryDataSourceRepository(),
        connector_registry=registry,
    )

    with TestClient(app) as client:
        source = client.post(
            "/api/data-sources",
            json={
                "name": "失败 MySQL",
                "engine": "mysql",
                "connection_config": {"host": "db.internal", "password": "private"},
            },
        ).json()
        tested = client.post(f"/api/data-sources/{source['id']}/test")

    assert tested.status_code == 200
    assert tested.json()["status"] == "failed"
    assert tested.json()["error_code"] == "connection_failed"
    assert "private" not in tested.text
    assert "driver" not in tested.text
    assert connectors[0].closed is True


class FakeConnectionTestConnector:
    capabilities = ConnectorCapabilities()

    def __init__(self, engine: str, *, fail: bool = False) -> None:
        self.engine = engine
        self.fail = fail
        self.pinged = False
        self.closed = False

    def ping(self) -> None:
        self.pinged = True
        if self.fail:
            raise DatabaseConnectorError(
                "connection_failed",
                "driver leaked private password",
            )

    def close(self) -> None:
        self.closed = True


def test_sync_mysql_databases_preserves_existing_and_marks_missing_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    repository = InMemoryDataSourceRepository()
    app = create_app(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        ),
        project_repository=InMemoryProjectRepository(),
        data_source_repository=repository,
    )
    monkeypatch.setattr(
        "context_router.api.data_sources.discover_databases",
        lambda source: [
            DiscoveredDatabase(name="app", system_database=False),
            DiscoveredDatabase(name="mysql", system_database=True),
        ],
    )
    invalidated_sources: list[str] = []
    monkeypatch.setattr(
        app.state.connector_manager,
        "invalidate_source",
        invalidated_sources.append,
    )

    with TestClient(app) as client:
        source = client.post(
            "/api/data-sources",
            json={
                "name": "远程 MySQL",
                "engine": "mysql",
                "connection_config": {
                    "host": "db.example.com",
                    "username": "reader",
                    "password": "secret",
                },
            },
        ).json()
        existing = client.post(
            f"/api/data-sources/{source['id']}/databases",
            json={
                "remote_name": "legacy",
                "display_name": "历史库",
                "namespace_type": "database",
            },
        ).json()
        synced = client.post(f"/api/data-sources/{source['id']}/databases/sync")

    assert synced.status_code == 200
    assert synced.json()["discovered_count"] == 2
    assert synced.json()["created_count"] == 2
    assert synced.json()["unavailable_count"] == 1
    databases = {item["remote_name"]: item for item in synced.json()["databases"]}
    assert databases["legacy"]["id"] == existing["id"]
    assert databases["legacy"]["available"] is False
    assert databases["app"]["available"] is True
    assert databases["mysql"]["system_database"] is True
    assert invalidated_sources == [source["id"]]
