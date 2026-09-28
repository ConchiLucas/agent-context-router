from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from test_postgres_persistence_integration import (
    isolated_postgres_database as isolated_postgres_database,
)

from alembic import command
from context_router.repositories.database_environment_repository import (
    PostgresDatabaseEnvironmentRepository,
)
from context_router.repositories.workspace_repository import PostgresWorkspaceRepository
from context_router.schemas.interface_forwarding import (
    BrowserInterfaceCapture,
    InterfaceForwardingBrowserCaptureImport,
    InterfaceForwardingEnvironmentWrite,
    InterfaceForwardingImport,
)
from context_router.services.interface_forwarding import InterfaceForwardingService

pytestmark = pytest.mark.postgresql


def test_durable_capture_lifecycle(isolated_postgres_database, monkeypatch):
    """Real PostgreSQL: original storage, rematch, revisions, dedup, savepoint isolation."""
    database_url = isolated_postgres_database
    monkeypatch.setenv("CONTEXT_ROUTER_DATABASE_URL", database_url)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "head")
    workspace = "durable-capture-test"
    PostgresWorkspaceRepository(database_url).create_workspace(
        workspace_id=workspace,
        name="录制回归测试",
        workspace_type="业务系统",
        root_path="/workspace/durable-capture-test",
    )
    service = InterfaceForwardingService(database_url)
    PostgresDatabaseEnvironmentRepository(database_url).upsert_environment(
        workspace_id=workspace,
        environment="local",
        display_name="LOCAL",
        sort_order=0,
    )

    def capture(id, path="/orders/save", **kwargs):
        return BrowserInterfaceCapture(
            capture_id=id,
            url="http://localhost:3000/rest/mtp" + path,
            method="POST",
            request_body={"password": "private", "id": 1},
            **kwargs,
        )

    def send(*captures, rematch=False):
        return service.import_browser_captures(
            InterfaceForwardingBrowserCaptureImport(
                workspace_id=workspace, environment_key="local", captures=list(captures)
            ),
            rematch=rematch,
        )

    # No forwarding configuration yet: the observation must nevertheless survive.
    first = send(capture("first", status_code=200, response_body={"ok": True}))
    assert first["stored_count"] == 1
    assert first["acknowledged"][0]["match_status"] == "pending"
    assert first["acknowledged"][0]["reason"] == "forwarding_configuration_missing"
    detail = service.browser_captures(workspace, capture_id="first")["records"][0]
    assert detail["payload"]["request_body"]["password"] == "[REDACTED]"
    imported = service.import_spec(
        InterfaceForwardingImport(
            workspace_id=workspace,
            service_name="capture-service",
            spec={
                "openapi": "3.0.0",
                "paths": {
                    "/orders/save": {"post": {"summary": "save", "responses": {}}},
                    "/orders/page": {"post": {"summary": "分页查询订单", "responses": {}}},
                    "/orders/{id}": {"post": {"summary": "template", "responses": {}}},
                },
            },
        )
    )
    service.create_environment(
        InterfaceForwardingEnvironmentWrite(
            workspace_id=workspace,
            environment_key="local",
            service_id=imported["service_id"],
            name="local",
            base_url="http://127.0.0.1:18880/rest/mtp",
        )
    )
    assert service.reconcile_browser_captures(workspace)["matched"] == 1
    logs = service.browser_captures(workspace, capture_id="first")["records"]
    log_id = logs[0]["log_id"]
    assert log_id
    # Repeated deliveries reuse the log, distinct identical calls do not collapse.
    assert send(capture("first"))["acknowledged"][0]["log_id"] == log_id
    assert send(capture("second"))["acknowledged"][0]["log_id"] != log_id
    # Read interfaces keep one representative sample per environment and local day.
    read_failed = send(capture("read-failed", "/orders/page", status_code=500))
    read_log_id = read_failed["acknowledged"][0]["log_id"]
    read_success = send(
        capture("read-success", "/orders/page", status_code=200, response_body={"rows": []})
    )
    assert read_success["acknowledged"][0]["log_id"] == read_log_id
    read_duplicate = send(
        capture("read-duplicate", "/orders/page", status_code=200, response_body={"rows": [1]})
    )
    assert read_duplicate["stored_count"] == 0
    assert read_duplicate["imported_count"] == 0
    assert read_duplicate["deduplicated_count"] == 1
    assert read_duplicate["acknowledged"][0]["status"] == "stored"
    assert read_duplicate["acknowledged"][0]["deduplicated"] is True
    assert read_duplicate["acknowledged"][0]["log_id"] == read_log_id
    enriched_duplicate = send(
        capture(
            "read-duplicate",
            "/orders/page",
            revision=2,
            status_code=200,
            response_body={"rows": [1], "enriched": True},
        )
    )
    assert enriched_duplicate["deduplicated_count"] == 1
    send(capture("lifecycle", capture_state="started"))
    final = send(capture("lifecycle", revision=2, status_code=201, response_body={"saved": True}))
    assert final["imported_count"] == 1
    send(capture("lifecycle", capture_state="started"))
    detail = service.browser_captures(workspace, capture_id="lifecycle")["records"][0]
    assert detail["revision"] == 2
    assert detail["payload"]["status_code"] == 201
    # Unknown route and long URL are both retained, rather than poisoning a batch.
    long_path = "/orders/save?q=" + "x" * 3000
    result = send(capture("unknown", "/not-in-spec"), capture("long", long_path))
    assert result["stored_count"] == 2
    assert result["imported_count"] == 1
    # An individual log INSERT failure must not roll back the original or its neighbour.
    original = service._import_browser_captures_matched

    def fail_one(payload, *, connection=None):
        if payload.captures[0].capture_id == "db-failure":
            connection.execute("SELECT 1/0")
        return original(payload, connection=connection)

    monkeypatch.setattr(service, "_import_browser_captures_matched", fail_one)
    result = send(capture("db-failure"), capture("healthy"))
    assert result["stored_count"] == 2
    assert result["acknowledged"][0]["reason"] == "matching_database_error"
    assert result["acknowledged"][1]["match_status"] == "matched"
    with psycopg.connect(database_url) as connection:
        assert (
            connection.execute("SELECT count(*) FROM browser_interface_captures").fetchone()[0] == 8
        )
        assert (
            connection.execute("SELECT count(*) FROM interface_forwarding_logs").fetchone()[0] == 6
        )
        daily = connection.execute(
            """SELECT browser_capture_id,browser_observed_count,browser_success_count,success
            FROM interface_forwarding_logs WHERE id=%s""",
            (read_log_id,),
        ).fetchone()
        assert daily == ("read-success", 3, 2, True)
    # Business rejection must not increment successes or replace a good daily sample.
    send(capture("business-error", "/orders/page", status_code=200, response_body={"code": 9000}))
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            "SELECT browser_capture_id,browser_observed_count,browser_success_count FROM "
            "interface_forwarding_logs WHERE id=%s",
            (read_log_id,),
        ).fetchone() == ("read-success", 4, 2)
    # Old extension decoded binary must survive both raw JSONB and matched text storage.
    result = send(capture("legacy-binary", status_code=200, response_body="PK\x00binary"))
    assert result["imported_count"] == 1
    # The first sample may be incomplete; enrichment must replace it and update success once.
    result = send(capture("missing", status_code=200, response_body_missing=True))
    missing_log_id = result["acknowledged"][0]["log_id"]
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            "SELECT success FROM interface_forwarding_logs WHERE id=%s", (missing_log_id,)
        ).fetchone() == (False,)
    send(
        capture(
            "missing",
            revision=2,
            status_code=200,
            response_body={"code": 200, "data": []},
            response_body_missing=False,
        )
    )
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            "SELECT success FROM interface_forwarding_logs WHERE id=%s", (missing_log_id,)
        ).fetchone() == (True,)

    # Each observation commits before matching the next one in the same HTTP batch.
    def check_previous_commit(payload, *, connection=None):
        if payload.captures[0].capture_id == "commit-second":
            with psycopg.connect(database_url) as reader:
                assert reader.execute(
                    "SELECT count(*) FROM browser_interface_captures WHERE capture_id=%s",
                    ("commit-first",),
                ).fetchone()[0] == 1
        return original(payload, connection=connection)

    monkeypatch.setattr(service, "_import_browser_captures_matched", check_previous_commit)
    assert send(capture("commit-first"), capture("commit-second"))["stored_count"] == 2
    # A competing row lock must reject only that capture, not hang or lose its neighbour.
    with psycopg.connect(database_url) as blocker:
        blocker.execute(
            "SELECT capture_id FROM browser_interface_captures WHERE capture_id=%s FOR UPDATE",
            ("commit-first",),
        )
        result = send(capture("commit-first", revision=2), capture("after-lock"))
        assert result["rejected"][0]["capture_id"] == "commit-first"
        assert result["acknowledged"][0]["capture_id"] == "after-lock"
