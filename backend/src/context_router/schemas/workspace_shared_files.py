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
