from datetime import datetime

from pydantic import BaseModel


class WorkspaceScriptSummary(BaseModel):
    id: str
    project_slug: str
    slug: str
    name: str
    description: str
    kind: str
    relative_path: str
    imported_at: datetime
    updated_at: datetime


class WorkspaceScriptDetail(WorkspaceScriptSummary):
    content: str


class WorkspaceScriptListResponse(BaseModel):
    project_slug: str
    scripts: list[WorkspaceScriptSummary]
