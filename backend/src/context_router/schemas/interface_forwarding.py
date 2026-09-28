from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from context_router.interface_search.domain import EndpointSemanticUpdate

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class InterfaceForwardingImport(BaseModel):
    workspace_id: str
    service_name: str = Field(min_length=1, max_length=160)
    spec: dict[str, Any]


class InterfaceForwardingNamedWrite(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class InterfaceSemanticsWrite(EndpointSemanticUpdate):
    """The merged navigator semantic contract; no legacy intent projection."""


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
    path_params: dict[str, str | int] = Field(default_factory=dict)


class InterfaceForwardingLogWrite(BaseModel):
    environment_id: str = Field(min_length=1, max_length=36)
    identity_id: str = Field(min_length=1, max_length=36)
    request_body: str = "{}"
    response_body: str = ""
    status_code: int | None = Field(default=None, ge=100, le=599)
    success: bool = False
    duration_ms: int = Field(ge=0)


class BrowserInterfaceCapture(BaseModel):
    """One sanitized browser network observation supplied by a trusted local client."""

    capture_id: str | None = Field(default=None, min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=16384)
    method: HttpMethod
    request_body: Any = None
    response_body: Any = None
    status_code: int | None = Field(default=None, ge=100, le=599)
    duration_ms: int = Field(default=0, ge=0, le=2_147_483_647)
    revision: int = Field(default=1, ge=1, le=2_147_483_647)
    capture_state: Literal["started", "complete", "incomplete"] = "complete"
    response_body_missing: bool = False

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class InterfaceForwardingBrowserCaptureImport(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=36)
    environment_id: str | None = Field(default=None, min_length=1, max_length=36)
    environment_key: str | None = Field(default=None, min_length=1, max_length=32)
    identity_id: str | None = Field(default=None, min_length=1, max_length=36)
    allow_origin_mismatch: bool = False
    captures: list[BrowserInterfaceCapture] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_environment_selector(self):
        if bool(self.environment_id) == bool(self.environment_key):
            raise ValueError("environment_id 与 environment_key 必须且只能提供一个")
        if self.identity_id and not self.environment_id:
            raise ValueError("identity_id 只能与 environment_id 一起使用")
        return self


class InterfaceForwardingOverview(BaseModel):
    workspace_id: str
    services: list[dict[str, Any]]
    environments: list[dict[str, Any]]
    interfaces: list[dict[str, Any]]
    selected_service_id: str
    interface_total: int
    page: int
    page_size: int
    total_pages: int


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
