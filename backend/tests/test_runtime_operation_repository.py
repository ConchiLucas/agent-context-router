from context_router.repositories.runtime_operation_repository import (
    InMemoryRuntimeOperationRepository,
    RuntimeOperationDraft,
    RuntimeOperationStepDraft,
    RuntimeStepResult,
)


def operation_draft() -> RuntimeOperationDraft:
    return RuntimeOperationDraft(
        task_id=7,
        workspace_id="workspace-1",
        kind="apply_changes",
        trigger="mcp",
        changed_files=("backend/app.py",),
        steps=(
            RuntimeOperationStepDraft(
                owner_type="project",
                owner_id="backend",
                mode="fast",
                snapshot_id="snapshot-1",
                snapshot_relative_path="projects/backend/fast/snapshot-1",
                changed_files=("app.py",),
                decision_reason="仅业务代码或资源文件发生变化",
                log_relative_path="runs/operation-1/step-1.log",
            ),
        ),
    )


def test_operation_repository_leases_one_operation_once() -> None:
    repository = InMemoryRuntimeOperationRepository()
    operation = repository.create_operation(operation_draft())

    assert operation.environment == "local"
    assert operation.action is None

    first = repository.lease_next(runner_id="runner-a", lease_seconds=30)
    second = repository.lease_next(runner_id="runner-b", lease_seconds=30)

    assert first is not None and first.operation.id == operation.id
    assert first.lease_token
    assert second is None


def test_operation_repository_completes_steps_and_parent() -> None:
    repository = InMemoryRuntimeOperationRepository()
    operation = repository.create_operation(operation_draft())
    lease = repository.lease_next(runner_id="runner-a", lease_seconds=30)
    assert lease is not None
    repository.mark_started(operation.id, lease.lease_token)
    step = repository.list_steps(operation.id)[0]

    completed = repository.complete_step(
        operation.id,
        step.id,
        lease.lease_token,
        RuntimeStepResult(exit_code=0),
    )

    assert completed.status == "succeeded"
    assert repository.list_steps(operation.id)[0].status == "succeeded"


def test_operation_repository_rejects_a_second_active_workspace_operation() -> None:
    repository = InMemoryRuntimeOperationRepository()
    repository.create_operation(operation_draft())

    try:
        repository.create_operation(operation_draft())
    except Exception as exc:
        assert "已有运行中的操作" in str(exc)
    else:
        raise AssertionError("second active Workspace operation must be rejected")


def test_operation_repository_supports_ui_project_update_without_task() -> None:
    repository = InMemoryRuntimeOperationRepository()
    draft = operation_draft()
    operation = repository.create_operation(
        RuntimeOperationDraft(
            task_id=None,
            workspace_id=draft.workspace_id,
            kind="project_update",
            trigger="ui",
            changed_files=(),
            steps=draft.steps,
        )
    )

    assert operation.task_id is None
    assert operation.kind == "project_update"
    assert repository.lease_next("runner-a", 30) is not None
