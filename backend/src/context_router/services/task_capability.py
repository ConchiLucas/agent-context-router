from __future__ import annotations

from typing import Literal

from context_router.repositories.task_capability_repository import (
    TaskCapabilityRepositoryError,
    TaskCapabilityStore,
)
from context_router.repositories.task_repository import TaskReader, TaskRepositoryError
from context_router.schemas.context import TaskIntentType

TaskCapability = Literal[
    "context.read",
    "task_context.read",
    "middleware.read",
    "relation.read",
    "mapping.read",
    "database.read",
    "interface.read",
    "interface.execute",
    "logs.read",
    "code.modify",
    "runtime.execute",
    "visualization.data.write",
    "visualization.task.write",
]

ALL_TASK_CAPABILITIES: frozenset[str] = frozenset(TaskCapability.__args__)
READ_ONLY_EXPANDABLE_CAPABILITIES: frozenset[str] = frozenset(
    {
        "context.read",
        "task_context.read",
        "middleware.read",
        "relation.read",
        "mapping.read",
        "database.read",
        "interface.read",
        "logs.read",
    }
)

_INITIAL_BY_INTENT: dict[TaskIntentType, tuple[str, ...]] = {
    "interface_discovery": (
        "context.read",
        "interface.read",
        "visualization.task.write",
    ),
    "interface_execute": (
        "context.read",
        "interface.read",
        "interface.execute",
        "visualization.task.write",
    ),
    "data_query": (
        "context.read",
        "mapping.read",
        "database.read",
        "visualization.data.write",
        "visualization.task.write",
    ),
    "task_execute": (
        "context.read",
        "runtime.execute",
        "visualization.task.write",
    ),
    "bug_investigate": ("context.read", "visualization.task.write"),
    "bug_fix": (
        "context.read",
        "code.modify",
        "interface.execute",
        "runtime.execute",
        "visualization.task.write",
    ),
    "code_change": (
        "context.read",
        "code.modify",
        "interface.execute",
        "runtime.execute",
        "visualization.task.write",
    ),
}

_HINT_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "context": ("context.read",),
    "database": ("mapping.read", "database.read"),
    "data": ("mapping.read", "database.read"),
    "interface": ("interface.read",),
    "logs": ("logs.read",),
    "middleware": ("middleware.read",),
    "relation": ("relation.read",),
    "mapping": ("mapping.read",),
}


class TaskCapabilityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TaskCapabilityService:
    def __init__(self, tasks: TaskReader, events: TaskCapabilityStore) -> None:
        self._tasks = tasks
        self._events = events

    @staticmethod
    def validate_hints(hints: list[str] | None) -> list[str]:
        normalized: list[str] = []
        for item in hints or []:
            value = item.strip().lower()
            if value not in _HINT_CAPABILITIES:
                raise TaskCapabilityError(
                    "capability_hint_not_supported",
                    f"不支持的能力提示：{item}",
                )
            if value not in normalized:
                normalized.append(value)
        return normalized

    def initialize(self, task_id: int, hints: list[str] | None = None) -> list[str]:
        try:
            task = self._tasks.get_task(task_id)
        except TaskRepositoryError as exc:
            raise TaskCapabilityError("task_not_found", str(exc)) from exc
        capabilities = list(_INITIAL_BY_INTENT[task.intent_type])
        if task.intent_error_signal and "logs.read" not in capabilities:
            capabilities.append("logs.read")
        normalized_hints = self.validate_hints(hints)
        for hint in normalized_hints:
            for capability in _HINT_CAPABILITIES[hint]:
                if (
                    capability in READ_ONLY_EXPANDABLE_CAPABILITIES
                    and capability not in capabilities
                ):
                    capabilities.append(capability)
        for capability in capabilities:
            self._enable(
                task_id=task_id,
                capability=capability,
                source="prepare",
                reason_code="intent_default" if not normalized_hints else "intent_or_hint",
            )
        return self.list_enabled(task_id)

    def enable_read_capability(
        self,
        task_id: int,
        capability: str,
        *,
        source: str,
        reason_code: str,
        evidence_call_id: int | None = None,
    ) -> list[str]:
        if capability not in READ_ONLY_EXPANDABLE_CAPABILITIES:
            raise TaskCapabilityError(
                "capability_not_expandable",
                f"能力 {capability} 不能通过只读发现自动启用",
            )
        self._enable(
            task_id=task_id,
            capability=capability,
            source=source,
            reason_code=reason_code,
            evidence_call_id=evidence_call_id,
        )
        return self.list_enabled(task_id)

    def list_enabled(self, task_id: int) -> list[str]:
        try:
            task = self._tasks.get_task(task_id)
            events = self._events.list_for_task(task_id)
        except (TaskRepositoryError, TaskCapabilityRepositoryError) as exc:
            raise TaskCapabilityError("task_capabilities_unavailable", str(exc)) from exc
        capabilities = set(_INITIAL_BY_INTENT[task.intent_type])
        if task.intent_error_signal:
            capabilities.add("logs.read")
        capabilities.update(
            (
                "interface.execute"
                if event.capability == "interface.execute_read"
                else event.capability
            )
            for event in events
        )
        return sorted(capabilities)

    def ensure_allowed(self, task_id: int, capability: str) -> None:
        try:
            task = self._tasks.get_task(task_id)
        except TaskRepositoryError as exc:
            raise TaskCapabilityError("task_not_found", str(exc)) from exc
        if capability in self.list_enabled(task_id):
            return
        if capability in READ_ONLY_EXPANDABLE_CAPABILITIES:
            self.enable_read_capability(
                task_id,
                capability,
                source="invocation",
                reason_code="recommended_or_explicit_action",
            )
            return
        if capability == "runtime.execute" and task.intent_type == "bug_investigate":
            raise TaskCapabilityError("mutation_forbidden", "Bug 查询任务禁止执行 Workspace 变更")
        raise TaskCapabilityError(
            "capability_not_enabled",
            f"当前任务未启用能力 {capability}",
        )

    def _enable(
        self,
        *,
        task_id: int,
        capability: str,
        source: str,
        reason_code: str,
        evidence_call_id: int | None = None,
    ) -> None:
        if capability not in ALL_TASK_CAPABILITIES:
            raise TaskCapabilityError("capability_not_supported", f"未知任务能力：{capability}")
        try:
            self._events.enable(
                task_id=task_id,
                capability=capability,
                source=source,
                reason_code=reason_code,
                evidence_call_id=evidence_call_id,
            )
        except TaskCapabilityRepositoryError as exc:
            raise TaskCapabilityError("task_capability_write_failed", str(exc)) from exc
