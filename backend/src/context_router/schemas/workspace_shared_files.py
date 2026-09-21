from pydantic import BaseModel


class WorkspaceSharedFilesResult(BaseModel):
    workspace_id: str
    source_root: str
    document_count: int
    deploy_count: int
    script_count: int
    host_runtime_count: int
    revision: int
    digest: str
    action: str


class WorkspaceScriptSummary(BaseModel):
    relative_path: str
    name: str
    description: str
    executable: bool
    content_sha256: str
    byte_size: int


class WorkspaceScriptDetail(WorkspaceScriptSummary):
    content: str


class WorkspaceScriptList(BaseModel):
    workspace_id: str
    revision: int | None
    target_directory: str
    scripts: list[WorkspaceScriptSummary]


class WorkspaceScriptSyncResult(BaseModel):
    workspace_id: str
    target_directory: str
    script_count: int
    revision: int


class WorkspaceTypedSyncResult(BaseModel):
    workspace_id: str
    file_types: list[str]
    target_directory: str
    file_count: int
    revision: int
