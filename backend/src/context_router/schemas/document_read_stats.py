from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DocumentReadStatItem(BaseModel):
    document_id: str
    document_path: str | None = None
    read_count: int
    task_count: int
    last_read_at: datetime


class DocumentReadTaskItem(BaseModel):
    task_id: int
    task: str
    agent_name: str | None = None
    cwd: str
    workspace_name: str | None = None
    active_project_name: str | None = None
    created_at: datetime
    read_count: int
    sections: list[str]
