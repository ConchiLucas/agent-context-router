from __future__ import annotations

from datetime import UTC, datetime

import pytest

from context_router.repositories.task_capability_repository import (
    InMemoryTaskCapabilityRepository,
)
from context_router.repositories.task_repository import TaskRecord
from context_router.services.task_capability import TaskCapabilityError, TaskCapabilityService


class _Tasks:
    def __init__(self, intent_type: str, *, error_signal: bool = False) -> None:
        self.record = TaskRecord(
            id=41,
            project_id="project-1",
            project_key="project",
            project_name="Project",
            task="test",
            cwd="/workspace",
            agent_name="codex",
            created_at=datetime.now(UTC),
            intent_type=intent_type,  # type: ignore[arg-type]
            intent_error_signal=error_signal,
        )

    def get_task(self, task_id: int) -> TaskRecord:
        assert task_id == 41
        return self.record


def test_prepare_initializes_intent_capabilities_and_safe_hints() -> None:
    service = TaskCapabilityService(
        _Tasks("code_change"),  # type: ignore[arg-type]
        InMemoryTaskCapabilityRepository(),
    )

    enabled = service.initialize(41, ["database", "logs"])

    assert "code.modify" in enabled
    assert "runtime.execute" in enabled
    assert "database.read" in enabled
    assert "mapping.read" in enabled
    assert "logs.read" in enabled


def test_bug_investigation_can_expand_reads_but_not_runtime_mutation() -> None:
    service = TaskCapabilityService(
        _Tasks("bug_investigate"),  # type: ignore[arg-type]
        InMemoryTaskCapabilityRepository(),
    )

    service.ensure_allowed(41, "database.read")
    assert "database.read" in service.list_enabled(41)

    with pytest.raises(TaskCapabilityError, match="禁止执行") as error:
        service.ensure_allowed(41, "runtime.execute")
    assert error.value.code == "mutation_forbidden"


def test_prepare_error_signal_enables_registered_log_inspection() -> None:
    service = TaskCapabilityService(
        _Tasks("bug_fix", error_signal=True),  # type: ignore[arg-type]
        InMemoryTaskCapabilityRepository(),
    )

    assert "logs.read" in service.initialize(41)


def test_interface_intent_enables_general_forwarding_execution() -> None:
    service = TaskCapabilityService(
        _Tasks("interface_execute"),  # type: ignore[arg-type]
        InMemoryTaskCapabilityRepository(),
    )

    enabled = service.initialize(41)

    assert "interface.execute" in enabled
    assert "interface.execute_read" not in enabled


def test_interface_discovery_enables_read_without_execution() -> None:
    service = TaskCapabilityService(
        _Tasks("interface_discovery"),  # type: ignore[arg-type]
        InMemoryTaskCapabilityRepository(),
    )

    enabled = service.initialize(41)

    assert "interface.read" in enabled
    assert "interface.execute" not in enabled


def test_interface_hint_does_not_grant_write_execution_to_investigation() -> None:
    service = TaskCapabilityService(
        _Tasks("bug_investigate"),  # type: ignore[arg-type]
        InMemoryTaskCapabilityRepository(),
    )

    enabled = service.initialize(41, ["interface"])

    assert "interface.read" in enabled
    assert "interface.execute" not in enabled
