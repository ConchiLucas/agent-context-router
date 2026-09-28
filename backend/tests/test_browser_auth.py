import json
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from test_postgres_persistence_integration import (
    isolated_postgres_database as isolated_postgres_database,
)

from alembic import command
from context_router.api.interface_forwarding import router
from context_router.middleware.browser_read_only import BrowserReadOnlyMiddleware
from context_router.repositories.database_environment_repository import (
    PostgresDatabaseEnvironmentRepository,
)
from context_router.repositories.workspace_repository import PostgresWorkspaceRepository
from context_router.schemas.interface_forwarding import (
    InterfaceForwardingEnvironmentWrite,
    InterfaceForwardingIdentityWrite,
    InterfaceForwardingImport,
)
from context_router.services.browser_auth import (
    BrowserAuthSync,
    matches_address,
    matches_system_code,
    selected_headers,
    sync_browser_auth,
)
from context_router.services.interface_forwarding import (
    InterfaceForwardingError,
    InterfaceForwardingService,
)
from context_router.services.interface_forwarding_context import InterfaceForwardingContextService


@pytest.mark.parametrize(
    "url,environment,base,expected",
    [
        (
            "http://example.test:18080/rest/mtp/order/page",
            "test",
            "http://example.test:18080/rest/mtp",
            True,
        ),
        (
            "http://example.test:28080/rest/mtp/order/page",
            "test",
            "http://example.test:18080/rest/mtp",
            False,
        ),
        (
            "http://localhost:3000/rest/mtp/order/page",
            "local",
            "http://127.0.0.1:18880/rest/mtp",
            True,
        ),
        (
            "http://localhost:3000/rest/mtp/order/page",
            "uat",
            "http://127.0.0.1:18880/rest/mtp",
            False,
        ),
        (
            "http://localhost:9999/rest/mtp/order/page",
            "local",
            "http://127.0.0.1:18880/rest/mtp",
            False,
        ),
        (
            "http://example.test:18080/rest/mtp-evil/page",
            "test",
            "http://example.test:18080/rest/mtp",
            False,
        ),
        (
            "http://user:secret@example.test:18080/rest/mtp/page",
            "test",
            "http://example.test:18080/rest/mtp",
            False,
        ),
    ],
)
def test_source_environment_boundary(url, environment, base, expected):
    assert matches_address(url, {"environment_key": environment, "base_url": base}) is expected


@pytest.mark.parametrize(
    "service_name,system_code,expected",
    [
        ("c12-mtp", "mtp", True),
        ("mtp", "mtp", True),
        ("c12-portal", "mtp", False),
        ("attempt", "mtp", False),
        ("c12-mtp", "../../mtp", False),
    ],
)
def test_system_code_matches_only_explicit_service_identity(service_name, system_code, expected):
    assert matches_system_code(service_name, system_code) is expected


def test_header_allowlist_and_redaction():
    values = {
        "_sid": SecretStr("fixture-token"),
        "Cookie": SecretStr("private-cookie"),
        "X-System-Code": SecretStr("mtp"),
        "Host": SecretStr("evil"),
    }
    assert selected_headers(values) == {"_sid": "fixture-token", "x-system-code": "mtp"}
    model = BrowserAuthSync(
        workspace_id="w",
        environment_key="local",
        url="http://localhost/",
        session_id="s",
        headers=values,
    )
    assert "fixture-token" not in repr(model)
    assert "fixture-token" not in model.model_dump_json()
    for value in ("null", "[REDACTED]", "bad\r\nheader", "x" * 8193):
        with pytest.raises(InterfaceForwardingError):
            selected_headers({"_sid": SecretStr(value)})


@pytest.mark.parametrize("account", [None, "browser-session:old", "BROWSER-SESSION:old"])
def test_anonymous_sync_skips_before_database_access(account):
    result = sync_browser_auth(
        object(),
        BrowserAuthSync(
            workspace_id="w",
            environment_key="local",
            url="http://localhost/",
            session_id="s",
            login_account=account,
            headers={"_sid": "fixture"},
        ),
    )
    assert result == {
        "status": "skipped",
        "reason": "verified_account_required",
        "identity_ids": [],
    }


def test_login_account_rejects_control_characters():
    with pytest.raises(ValidationError):
        BrowserAuthSync(
            workspace_id="w",
            environment_key="local",
            url="http://localhost/",
            session_id="s",
            login_account="bad\naccount",
            headers={"_sid": "fixture"},
        )


def test_address_names_are_trimmed_deduplicated_and_reject_control_characters():
    payload = BrowserAuthSync(
        workspace_id="w",
        environment_key="local",
        url="http://localhost/",
        session_id="s",
        address_names=[" 门户端 ", "门户端"],
        headers={"_sid": "fixture"},
    )
    assert payload.address_names == ["门户端"]
    with pytest.raises(ValidationError):
        BrowserAuthSync(
            workspace_id="w",
            environment_key="local",
            url="http://localhost/",
            session_id="s",
            address_names=["门户端\n运营端"],
            headers={"_sid": "fixture"},
        )


def test_browser_origin_rejected_before_sync():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.add_middleware(BrowserReadOnlyMiddleware, api_prefix="/api")
    result = TestClient(app).post(
        "/api/interface-forwarding/browser-captures/auth",
        headers={"Origin": "http://evil.test"},
        json={
            "workspace_id": "w",
            "environment_key": "local",
            "url": "http://localhost/",
            "session_id": "s",
            "headers": {"_sid": "fixture"},
        },
    )
    assert result.status_code == 403
    assert "fixture" not in result.text


@pytest.mark.postgresql
def test_sync_isolated_database_and_forwarding(isolated_postgres_database, monkeypatch):
    database_url = isolated_postgres_database
    monkeypatch.setenv("CONTEXT_ROUTER_DATABASE_URL", database_url)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "head")
    workspace = "browser-auth-test"
    PostgresWorkspaceRepository(database_url).create_workspace(
        workspace_id=workspace,
        name="Header test",
        workspace_type="业务系统",
        root_path="/workspace/auth-test",
    )
    envs = PostgresDatabaseEnvironmentRepository(database_url)
    service = InterfaceForwardingService(database_url)
    imported = service.import_spec(
        InterfaceForwardingImport(
            workspace_id=workspace,
            service_name="c12-mtp",
            spec={
                "openapi": "3.0.0",
                "paths": {"/orders/page": {"post": {"summary": "page", "responses": {}}}},
            },
        )
    )
    for index, (key, port) in enumerate((("local", 18880), ("test", 18080), ("uat", 28080))):
        envs.upsert_environment(
            workspace_id=workspace, environment=key, display_name=key, sort_order=index
        )
        service.create_environment(
            InterfaceForwardingEnvironmentWrite(
                workspace_id=workspace,
                environment_key=key,
                service_id=imported["service_id"],
                name=key,
                base_url=f"http://127.0.0.1:{port}/rest/mtp",
            )
        )

    portal_address = service.create_environment(
        InterfaceForwardingEnvironmentWrite(
            workspace_id=workspace,
            environment_key="test",
            service_id=imported["service_id"],
            name="门户端",
            base_url="http://127.0.0.1:18080/rest/mtp",
        )
    )

    def sync(
        key,
        port,
        session="session-a",
        token="fixture-token",
        login_account=None,
        address_names=None,
        role_name="",
    ):
        return sync_browser_auth(
            service,
            BrowserAuthSync(
                workspace_id=workspace,
                environment_key=key,
                url=f"http://127.0.0.1:{port}/rest/mtp/orders/page",
                session_id=session,
                login_account=login_account or "fixture-" + session,
                address_names=address_names or [],
                role_name=role_name,
                headers={"_sid": token, "X-System-Code": "mtp"},
            ),
        )

    first = sync("test", 18080)
    assert "fixture-token" not in json.dumps(first)
    assert sync("test", 18080)["identity_ids"] == first["identity_ids"]
    before = service.list_identities(workspace)[0]["updated_at"]
    sync("test", 18080)
    assert service.list_identities(workspace)[0]["updated_at"] == before
    # Operations keeps one empty-role identity per account/address, even when
    # the page reports different casing or refreshes its session after login.
    refreshed = sync("test", 18080, token="renewed-token", login_account="FIXTURE-SESSION-A")
    assert set(refreshed["identity_ids"]) == set(first["identity_ids"])
    assert all(
        row["request_header"].find("renewed-token") >= 0
        for row in service.list_identities(workspace)
    )
    sync("test", 18080)
    sync("uat", 28080, token="uat-token")
    with pytest.raises(InterfaceForwardingError):
        sync("local", 28080)
    sync("local", 3000, token="local-token")
    rows = service.list_identities(workspace)
    assert len(rows) == 4
    by_env = {row["environment_key"]: row for row in rows if row["environment_name"] != "门户端"}
    for key in ("local", "uat", "test"):
        expected = "fixture-token" if key == "test" else key + "-token"
        assert InterfaceForwardingContextService._request_headers(by_env[key])["_sid"] == expected
    # Other browser credentials never overwrite an existing session identity.
    sync("test", 18080, session="session-b", token="another-token")
    assert len(service.list_identities(workspace)) == 6

    portal = sync(
        "test",
        18080,
        session="portal-session",
        token="portal-token",
        login_account="portal-user",
        address_names=["门户端"],
    )
    assert len(portal["identity_ids"]) == 1
    assert (
        next(
            row
            for row in service.list_identities(workspace)
            if row["id"] == portal["identity_ids"][0]
        )["environment_id"]
        == portal_address["id"]
    )

    # A confirmed account promotes the matching anonymous credential in place.
    anonymous_id = service.create_identity(
        InterfaceForwardingIdentityWrite(
            workspace_id=workspace,
            environment_id=by_env["local"]["environment_id"],
            login_account="browser-session:legacy",
            request_header=json.dumps({"_sid": "promote-token", "x-system-code": "mtp"}),
        )
    )["id"]
    promoted = sync(
        "local",
        3000,
        session="session-c",
        token="promote-token",
        login_account="superadmin",
    )
    assert promoted["identity_ids"] == [anonymous_id]
    promoted_row = next(
        row for row in service.list_identities(workspace) if row["id"] == anonymous_id
    )
    assert promoted_row["login_account"] == "superadmin"
    assert len(service.list_identities(workspace)) == 8

    # The same verified session promotes an unnamed role without copying it
    # to other services/environments; later role switches remain independent.
    role = sync("local", 3000, token="promote-token", login_account="superadmin", role_name="货主")
    assert role["identity_ids"] == [anonymous_id]
    assert role["role_name"] == "货主"
    assert (
        next(row for row in service.list_identities(workspace) if row["id"] == anonymous_id)[
            "role_name"
        ]
        == "货主"
    )
    other = sync(
        "local", 3000, token="carrier-token", login_account="superadmin", role_name="承运商"
    )
    assert other["identity_ids"] != role["identity_ids"]

    # One observed operations request updates all explicitly grouped services.
    from context_router.services import browser_auth

    target_ids = set()
    excluded_ids = set()
    for name in ("c12-mtp", "c12-sys", "c12-portal", "c12-admin"):
        imported_group = service.import_spec(
            InterfaceForwardingImport(
                workspace_id=workspace,
                service_name=name,
                spec={"openapi": "3.0.0", "paths": {"/read": {"get": {"responses": {}}}}},
            )
        )
        for address_name, port in (("运营端", 28080), ("门户端", 28080), ("其他运营端", 28081)):
            address = service.create_environment(
                InterfaceForwardingEnvironmentWrite(
                    workspace_id=workspace,
                    environment_key="uat",
                    service_id=imported_group["service_id"],
                    name=address_name,
                    base_url=f"http://127.0.0.1:{port}/rest/{name.removeprefix('c12-')}",
                )
            )
            (
                target_ids
                if address_name == "运营端" and port == 28080 and name != "c12-admin"
                else excluded_ids
            ).add(address["id"])
    monkeypatch.setattr(
        browser_auth,
        "SHARED_LOGIN_GROUPS",
        (
            {
                **browser_auth.SHARED_LOGIN_GROUPS[0],
                "workspace_id": workspace,
                "origin": "http://127.0.0.1:28080",
            },
        ),
    )
    payload = BrowserAuthSync(
        workspace_id=workspace,
        environment_key="uat",
        url="http://127.0.0.1:28080/rest/sys/system/login/getLoginUserInfo",
        session_id="shared-login",
        login_account="superadmin",
        address_names=["运营端"],
        headers={"_sid": "shared-first", "x-system-code": "mtp"},
    )
    created = sync_browser_auth(service, payload)
    assert len(created["identity_ids"]) == 3
    payload.headers = {"_sid": SecretStr("shared-renewed"), "x-system-code": SecretStr("mtp")}
    payload.login_account = "superAdmin"
    updated = sync_browser_auth(service, payload)
    assert set(updated["identity_ids"]) == set(created["identity_ids"])
    shared = [r for r in service.list_identities(workspace) if r["id"] in updated["identity_ids"]]
    assert {r["environment_id"] for r in shared} == target_ids
    assert all(r["login_account"] == "superadmin" for r in shared)
    assert all(
        json.loads(r["request_header"]) == {"_sid": "shared-renewed", "x-system-code": "mtp"}
        for r in shared
    )
    assert not any(r["environment_id"] in excluded_ids for r in service.list_identities(workspace))


@pytest.mark.parametrize(
    "change",
    [
        {"workspace_id": "other"},
        {"environment_key": "test"},
        {"url": "http://192.168.0.222:18080/rest/sys/read"},
        {"address_names": ["门户端"]},
        {"address_names": []},
        {"role_name": "货主"},
    ],
)
def test_shared_login_does_not_expand_outside_explicit_group(change):
    from context_router.services.browser_auth import SHARED_LOGIN_GROUPS, shared_login_addresses

    group = SHARED_LOGIN_GROUPS[0]
    payload = BrowserAuthSync(
        **(
            {
                "workspace_id": group["workspace_id"],
                "environment_key": "uat",
                "url": group["origin"] + "/rest/sys/read",
                "session_id": "fixture",
                "login_account": "superadmin",
                "address_names": ["运营端"],
                "headers": {"_sid": "fixture"},
            }
            | change
        )
    )
    addresses = [
        {
            "id": name,
            "environment_key": "uat",
            "name": "运营端",
            "service_name": "c12-" + name,
            "base_url": group["origin"] + "/rest/" + name,
        }
        for name in ("mtp", "sys", "portal")
    ]
    assert shared_login_addresses(payload, addresses, [addresses[1]]) == [addresses[1]]


@pytest.mark.parametrize(
    "environment,origin",
    [
        ("uat", "http://192.168.0.222:28080"),
        ("test", "http://192.168.0.222:18080"),
        ("pre", "http://223.87.29.28:30080"),
        *(
            ("local", f"http://{host}:{port}")
            for host in ("localhost", "127.0.0.1")
            for port in (3000, 3001)
        ),
    ],
)
def test_each_environment_shared_login_stays_in_its_operations_group(environment, origin):
    from context_router.services.browser_auth import SHARED_LOGIN_GROUPS, shared_login_addresses

    payload = BrowserAuthSync(
        workspace_id=SHARED_LOGIN_GROUPS[0]["workspace_id"],
        environment_key=environment,
        url=origin + "/rest/sys/read",
        session_id="fixture",
        login_account="superadmin",
        address_names=["运营端"],
        headers={"_sid": "fixture"},
    )
    target_origin = "http://127.0.0.1:18880" if environment == "local" else origin
    targets = [
        {
            "id": name,
            "environment_key": environment,
            "name": "运营端",
            "service_name": "c12-" + name,
            "base_url": target_origin + "/rest/" + name,
        }
        for name in ("mtp", "sys", "portal")
    ]
    excluded = [dict(row, id="portal-" + row["id"], name="门户端") for row in targets]
    excluded += [dict(row, id="other-env-" + row["id"], environment_key="other") for row in targets]
    excluded += [
        dict(row, id="other-origin-" + row["id"], base_url="http://elsewhere.test/rest/mtp")
        for row in targets
    ]
    assert shared_login_addresses(payload, targets + excluded, [targets[1]]) == targets
    assert shared_login_addresses(payload, targets + excluded, []) == []


@pytest.mark.parametrize(
    "environment,origin",
    [
        ("test", "http://192.168.0.222:18080"),
        ("uat", "http://192.168.0.222:28080"),
        ("pre", "http://223.87.29.28:30080"),
    ],
)
def test_driver_h5_facade_session_maps_only_to_mtp_driver_address(environment, origin):
    from context_router.services.browser_auth import driver_h5_login_addresses

    payload = BrowserAuthSync(
        workspace_id="b9ce65eddc27437d9615177fbd07cb0a",
        environment_key=environment,
        url=origin + "/rest/facade/api/app/auth/getLoginUserInfo",
        session_id="driver-fixture",
        login_account="18900006666",
        address_names=["司机端"],
        headers={"_sid": "fixture-token", "x-system-code": "app"},
    )
    target = {
        "id": "driver",
        "environment_key": environment,
        "name": "司机端",
        "service_name": "c12-mtp",
        "base_url": origin + "/rest/mtp",
    }
    excluded = [
        dict(target, id="portal", name="门户端"),
        dict(target, id="other-environment", environment_key="other"),
        dict(target, id="other-origin", base_url="http://elsewhere.test/rest/mtp"),
        dict(target, id="other-service", service_name="c12-portal"),
    ]
    assert driver_h5_login_addresses(payload, [target, *excluded], {"x-system-code": "app"}) == [
        target
    ]
    current_page = BrowserAuthSync.model_validate(
        payload.model_dump()
        | {"url": origin + "/rest/facade/member-api/mtp/highway/dispatchOrder/page"}
    )
    assert driver_h5_login_addresses(current_page, [target], {"x-system-code": "app"}) == [target]
    for changes in (
        {"address_names": ["门户端"]},
        {"role_name": "司机"},
        {"url": origin + "/rest/mtp/admin/driver/mobile/current"},
        {"url": origin + "/rest/facade-other/api/app/auth/getLoginUserInfo"},
        {"workspace_id": "other"},
    ):
        changed = BrowserAuthSync.model_validate(payload.model_dump() | changes)
        assert (
            driver_h5_login_addresses(changed, [target, *excluded], {"x-system-code": "app"}) == []
        )
    assert driver_h5_login_addresses(payload, [target], {"x-system-code": "portal"}) == []
