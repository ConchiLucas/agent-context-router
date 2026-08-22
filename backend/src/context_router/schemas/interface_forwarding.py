from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class InterfaceForwardingImport(BaseModel):
    workspace_id: str
    service_name: str = Field(min_length=1, max_length=160)
    spec: dict[str, Any]


class InterfaceForwardingNamedWrite(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class InterfaceForwardingEnvironmentWrite(BaseModel):
    workspace_id: str
    environment_key: str = Field(min_length=1, max_length=32)
    service_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=1000)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("转发地址必须以 http:// 或 https:// 开头")
        return normalized


class InterfaceForwardingIdentityWrite(BaseModel):
    workspace_id: str
    environment_id: str = Field(min_length=1, max_length=36)
    login_account: str = Field(min_length=1, max_length=240)
    role_name: str = Field(default="", max_length=160)
    request_header: str = ""


class InterfaceForwardingExecute(BaseModel):
    environment_id: str
    identity_id: str | None = None
    request_body: str = "{}"


class InterfaceForwardingLogWrite(BaseModel):
    environment_id: str = Field(min_length=1, max_length=36)
    identity_id: str = Field(min_length=1, max_length=36)
    request_body: str = "{}"
    response_body: str = ""
    status_code: int | None = Field(default=None, ge=100, le=599)
    success: bool = False
    duration_ms: int = Field(ge=0)


class InterfaceForwardingOverview(BaseModel):
    workspace_id: str
    services: list[dict[str, Any]]
    environments: list[dict[str, Any]]


class InterfaceForwardingResult(BaseModel):
    success: bool
    status_code: int | None = None
    duration_ms: int
    response_body: str
    response_headers: dict[str, str] = Field(default_factory=dict)


class InterfaceForwardingRewriteResult(BaseModel):
    workspace_id: str
    service_id: str | None = None
    total: int
    updated: int


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
