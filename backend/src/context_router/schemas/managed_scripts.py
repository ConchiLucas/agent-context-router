from pydantic import BaseModel, Field


class ManagedScriptWorkspace(BaseModel):
    id: str
    name: str


class ManagedScript(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    kind: str
    action_key: str
    workspace_id: str | None
    workspace_name: str | None
    command_path: str | None
    autostart_enabled: bool
    autostart_installed: bool
    available: bool
    unavailable_reason: str | None = None


class ManagedScriptList(BaseModel):
    scripts: list[ManagedScript]
    workspaces: list[ManagedScriptWorkspace]


class ManagedScriptAutostartUpdate(BaseModel):
    enabled: bool


class ManagedScriptRunRequest(BaseModel):
    workspace_id: str | None = Field(default=None, max_length=32)


class ManagedScriptRunResult(BaseModel):
    script_id: str
    action: str
    workspace_id: str | None = None
    message: str
