"""Environment-scoped browser credentials, separate from sanitized request logs."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, Field, SecretStr, field_validator

from context_router.services.interface_forwarding import InterfaceForwardingError

# Explicit shared-login boundaries: operations services share a session per environment.
# Keep portal identities, management addresses and other environments independent.
SHARED_LOGIN_GROUPS = tuple(
    {
        "workspace_id": "b9ce65eddc27437d9615177fbd07cb0a",
        "environment_key": environment,
        "origin": origin,
        "address_name": "运营端",
        "services": frozenset({"c12-mtp", "c12-sys", "c12-portal"}),
    }
    for environment, origin in (
        ("uat", "http://192.168.0.222:28080"),
        ("test", "http://192.168.0.222:18080"),
        ("pre", "http://223.87.29.28:30080"),
        *(
            ("local", f"http://{host}:{port}")
            for host in ("localhost", "127.0.0.1")
            for port in (3000, 3001)
        ),
    )
)

DRIVER_H5_LOGIN_ORIGINS = {
    "test": "http://192.168.0.222:18080",
    "uat": "http://192.168.0.222:28080",
    "pre": "http://223.87.29.28:30080",
}


def driver_h5_login_addresses(payload, addresses, headers):
    """Map a verified H5 app request on the facade only to the MTP driver address."""
    source = urlsplit(payload.url)
    origin = DRIVER_H5_LOGIN_ORIGINS.get(payload.environment_key)
    if (
        payload.workspace_id != "b9ce65eddc27437d9615177fbd07cb0a"
        or not origin
        or f"{source.scheme}://{source.netloc}" != origin
        or not source.path.startswith("/rest/facade/")
        or payload.address_names != ["司机端"]
        or payload.role_name
        or headers.get("x-system-code", "").lower() != "app"
    ):
        return []
    return [
        row
        for row in addresses
        if row["environment_key"] == payload.environment_key
        and row["service_name"] == "c12-mtp"
        and row["name"] == "司机端"
        and matches_address_origin(payload.url, row)
    ]


def shared_login_addresses(payload, addresses, matches):
    source = urlsplit(payload.url)
    for group in SHARED_LOGIN_GROUPS:
        if (
            payload.workspace_id != group["workspace_id"]
            or payload.environment_key != group["environment_key"]
            or f"{source.scheme}://{source.netloc}" != group["origin"]
            or payload.address_names != [group["address_name"]]
            or payload.role_name
        ):
            continue
        targets = [
            row
            for row in addresses
            if row["environment_key"] == group["environment_key"]
            and row["name"] == group["address_name"]
            and row["service_name"] in group["services"]
            and matches_address_origin(payload.url, row)
        ]
        if any(row in targets for row in matches):
            return targets
    return matches


class BrowserAuthSync(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=36)
    environment_key: str = Field(min_length=1, max_length=32)
    url: str = Field(min_length=1, max_length=16384)
    session_id: str = Field(pattern=r"^[a-zA-Z0-9-]{1,80}$")
    login_account: str | None = Field(default=None, min_length=1, max_length=240)
    role_name: str = Field(default="", max_length=160)
    address_names: list[str] = Field(default_factory=list, max_length=8)
    headers: dict[str, SecretStr] = Field(min_length=1, max_length=8)

    @field_validator("role_name")
    @classmethod
    def validate_role_name(cls, value: str) -> str:
        if any(character in value for character in "\r\n\x00"):
            raise ValueError("角色名称无效")
        return value.strip()

    @field_validator("login_account")
    @classmethod
    def validate_login_account(cls, value: str | None) -> str | None:
        if value is None:
            return None
        account = value.strip()
        if not account or any(character in account for character in "\r\n\x00"):
            raise ValueError("登录账号无效")
        return account

    @field_validator("address_names")
    @classmethod
    def validate_address_names(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            name = value.strip()
            if not name or len(name) > 160 or any(character in name for character in "\r\n\x00"):
                raise ValueError("转发地址名称无效")
            if name.casefold() not in {item.casefold() for item in result}:
                result.append(name)
        return result


def selected_headers(values: dict[str, SecretStr]) -> dict[str, str]:
    result = {}
    for name, secret in values.items():
        key, value = name.lower(), secret.get_secret_value().strip()
        if key not in {"_sid", "x-system-code", "authorization"}:
            continue
        if not value or len(value) > 8192 or any(c in value for c in "\r\n\x00"):
            raise InterfaceForwardingError("登录请求头无效")
        if value.lower() in {"null", "undefined", "[redacted]"}:
            raise InterfaceForwardingError("登录请求头无效")
        result[key] = value
    if not (result.get("_sid") or result.get("authorization")):
        raise InterfaceForwardingError("缺少登录请求头")
    return result


def matches_address_origin(url: str, address: dict) -> bool:
    source, target = urlsplit(url), urlsplit(address["base_url"])
    if source.username or source.password or source.scheme not in {"http", "https"}:
        return False

    def origin(parts):
        return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)

    try:
        same = origin(source) == origin(target)
    except ValueError:
        return False
    local_proxy = (
        address["environment_key"] == "local"
        and source.scheme == target.scheme == "http"
        and source.hostname in {"localhost", "127.0.0.1"}
        and target.hostname in {"localhost", "127.0.0.1"}
        and source.port in {3000, 3001}
        and target.port == 18880
    )
    return same or local_proxy


def matches_address(url: str, address: dict) -> bool:
    source, target = urlsplit(url), urlsplit(address["base_url"])
    prefix = target.path.rstrip("/")
    return matches_address_origin(url, address) and (
        source.path == prefix or source.path.startswith(prefix + "/")
    )


def matches_system_code(service_name: str, system_code: str) -> bool:
    code = system_code.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", code):
        return False
    tokens = [part for part in re.split(r"[^a-z0-9]+", service_name.strip().lower()) if part]
    return bool(tokens and tokens[-1] == code)


def sync_browser_auth(service, payload: BrowserAuthSync) -> dict:
    account = (payload.login_account or "").strip()
    if not account or account.casefold().startswith("browser-session:"):
        return {"status": "skipped", "reason": "verified_account_required", "identity_ids": []}
    headers = selected_headers(payload.headers)
    if not account or any(character in account for character in "\r\n\x00"):
        raise InterfaceForwardingError("登录账号无效")
    encoded_headers = json.dumps(headers)
    with service._connect() as connection, connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '1500ms'")
        cursor.execute("SET LOCAL statement_timeout = '5000ms'")
        cursor.execute(
            "SELECT environment.id, environment.environment_key, environment.name, "
            "environment.base_url, "
            "service.name AS service_name FROM interface_forwarding_environments environment "
            "JOIN interface_forwarding_services service ON service.id=environment.service_id "
            "WHERE environment.workspace_id=%s",
            (payload.workspace_id,),
        )
        addresses = list(cursor.fetchall())
        matches = [row for row in addresses if matches_address(payload.url, row)]
        system_code = headers.get("x-system-code", "")
        if not matches and system_code:
            matches = [
                row
                for row in addresses
                if row["environment_key"] == payload.environment_key
                and matches_address_origin(payload.url, row)
                and matches_system_code(row["service_name"], system_code)
            ]
        if payload.address_names:
            requested_names = {name.casefold() for name in payload.address_names}
            matches = [row for row in matches if str(row["name"]).casefold() in requested_names]
        if not matches:
            matches = driver_h5_login_addresses(payload, addresses, headers)
        if not matches or any(row["environment_key"] != payload.environment_key for row in matches):
            raise InterfaceForwardingError("采集来源与环境不匹配或存在歧义")
        matches = shared_login_addresses(payload, addresses, matches)
        ids = []
        for address in sorted(matches, key=lambda row: str(row["id"])):
            if payload.login_account:
                cursor.execute(
                    "SELECT id FROM interface_forwarding_identities "
                    "WHERE environment_id=%s AND role_name='' AND "
                    "(login_account LIKE 'browser-session:%%' OR "
                    "(%s<>'' AND lower(login_account)=lower(%s))) "
                    "AND request_header=%s ORDER BY updated_at DESC LIMIT 1",
                    (address["id"], payload.role_name, account, encoded_headers),
                )
                anonymous = cursor.fetchone()
                cursor.execute(
                    "SELECT id FROM interface_forwarding_identities "
                    "WHERE environment_id=%s AND lower(login_account)=lower(%s) "
                    "AND lower(role_name)=lower(%s) LIMIT 1",
                    (address["id"], account, payload.role_name),
                )
                named = cursor.fetchone()
                if anonymous and not named:
                    cursor.execute(
                        "UPDATE interface_forwarding_identities "
                        "SET login_account=%s, role_name=%s, updated_at=now() "
                        "WHERE id=%s RETURNING id",
                        (account, payload.role_name, anonymous["id"]),
                    )
                    ids.append(str(cursor.fetchone()["id"]))
                    continue
            cursor.execute(
                "INSERT INTO interface_forwarding_identities "
                "(id, workspace_id, environment_id, login_account, role_name, request_header) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (environment_id, lower(login_account), lower(role_name)) "
                "DO UPDATE SET request_header=EXCLUDED.request_header, "
                "updated_at=CASE WHEN interface_forwarding_identities.request_header "
                "IS DISTINCT FROM EXCLUDED.request_header THEN now() "
                "ELSE interface_forwarding_identities.updated_at END "
                "RETURNING id",
                (
                    str(uuid4()),
                    payload.workspace_id,
                    address["id"],
                    account,
                    payload.role_name,
                    encoded_headers,
                ),
            )
            ids.append(str(cursor.fetchone()["id"]))
    return {
        "status": "synced",
        "environment": payload.environment_key,
        "identity_ids": ids,
        "login_account": account,
        "role_name": payload.role_name,
        "header_names": sorted(headers),
    }
