from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PromptMatchVerdict = Literal["resolved", "needs_selection", "no_candidate"]
PromptClientName = Literal[
    "codex",
    "codex-root",
    "codex-astra",
    "cursor",
    "antigravity",
    "grok-heavy",
]
PromptClientStatus = Literal[
    "missing",
    "searching",
    "selected",
    "clarify",
    "violated",
    "failed",
]


class InterfacePromptMatchCandidate(BaseModel):
    interface_id: str
    method: str
    path: str
    title: str
    service: str = ""
    controller_name: str = ""
    audiences: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    resource: str = ""
    actions: list[str] = Field(default_factory=list)
    discriminators: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    matched_slots: list[str] = Field(default_factory=list)
    conflicting_slots: list[str] = Field(default_factory=list)


class InterfacePromptIdentity(BaseModel):
    interface_id: str | None = None
    method: str = ""
    path: str = ""
    title: str = ""
    service: str = ""


class InterfacePromptClientJudgment(BaseModel):
    client: PromptClientName
    status: PromptClientStatus
    task_id: int | None = None
    selected_interface_id: str | None = None
    selected_method: str | None = None
    selected_path: str | None = None
    selected_title: str | None = None
    in_candidates: bool | None = None
    compared: bool = False
    compared_interface_ids: list[str] = Field(default_factory=list)
    detailed_interface_ids: list[str] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)
    prohibited_tool_calls: list[str] = Field(default_factory=list)
    reason: str = ""


class InterfacePromptMatch(BaseModel):
    id: str
    workspace_id: str
    environment_key: str
    prompt: str
    verdict: PromptMatchVerdict
    first_interface_id: str | None = None
    candidates: list[InterfacePromptMatchCandidate] = Field(default_factory=list)
    remaining_count: int = 0
    search_id: str
    reason: str = ""
    differing_dimensions: list[str] = Field(default_factory=list)
    created_at: datetime
    note: str = ""
    expected: InterfacePromptIdentity | None = None
    clients: list[InterfacePromptClientJudgment] = Field(default_factory=list)


class InterfacePromptMatchList(BaseModel):
    items: list[InterfacePromptMatch]
    total: int = 0
    page: int = 1
    page_size: int = 20


class InterfacePromptMatchCreate(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=120)
    environment_key: str = Field(default="local", max_length=32)
    prompt: str = Field(min_length=1, max_length=2000)
    expected_interface_id: str | None = Field(default=None, max_length=120)
    note: str = Field(default="", max_length=500)


class InterfacePromptClientResultReset(BaseModel):
    workspace_id: str
    client: Literal["antigravity"] = "antigravity"
    matched_task_count: int = 0
    matched_tool_call_count: int = 0
    deleted_task_count: int = 0


class InterfacePromptClientResultImportItem(BaseModel):
    record_id: str = Field(min_length=1, max_length=36)
    client: PromptClientName
    task_id: int = Field(ge=1)
    batch_id: str = Field(min_length=1, max_length=32)
    model: str = Field(default="", max_length=160)
    reasoning_effort: str = Field(default="", max_length=64)
    source_file: str = Field(min_length=1, max_length=2000)
    status: Literal["selected", "needs_clarification", "tool_failure"]
    selected_interface_id: str | None = Field(default=None, max_length=120)
    clarification_question: str | None = Field(default=None, max_length=2000)
    ambiguity_dimensions: list[str] = Field(default_factory=list, max_length=100)
    candidate_interface_ids: list[str] = Field(default_factory=list, max_length=100)
    compared_interface_ids: list[str] = Field(default_factory=list, max_length=100)
    searched: bool = False
    compared: bool = False
    detail_read: bool = False


class InterfacePromptClientResultImport(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=120)
    records: list[InterfacePromptClientResultImportItem] = Field(min_length=1, max_length=100)


class InterfacePromptClientResultImportResponse(BaseModel):
    workspace_id: str
    imported_count: int


class InterfacePromptClientStoredResultReset(BaseModel):
    workspace_id: str
    client: PromptClientName
    matched_result_count: int
    deleted_result_count: int
