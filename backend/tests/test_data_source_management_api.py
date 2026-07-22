from pathlib import Path

from fastapi.testclient import TestClient

from context_router.config import Settings
from context_router.main import create_app
from context_router.repositories.data_source_repository import InMemoryDataSourceRepository
from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.services.database_discovery import DiscoveredDatabase


def test_data_source_database_and_project_link_crud(tmp_path: Path) -> None:
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
    assert listed_sources.json()[0]["database_count"] == 1
    assert listed_sources.json()[0]["project_count"] == 1
    assert listed_databases.json()[0]["project_count"] == 1
    assert listed_project_databases.json()[0]["database_name"] == "orders"
    assert deleted_link.status_code == 204
    assert deleted_database.status_code == 204
    assert deleted_source.status_code == 204


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
    assert duplicate.status_code == 400


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
