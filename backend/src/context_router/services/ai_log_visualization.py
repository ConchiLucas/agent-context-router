from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from context_router.repositories.ai_log_investigation_repository import (
    AiLogInvestigationRecord,
    AiLogInvestigationRepositoryError,
    AiLogInvestigationStore,
)
from context_router.repositories.project_repository import ProjectRepositoryError, ProjectStore
from context_router.repositories.task_repository import TaskRepositoryError, TaskStore
from context_router.repositories.workspace_repository import (
    WorkspaceRepositoryError,
    WorkspaceStore,
)
from context_router.schemas.ai_log_visualization import (
    AiLogInvestigationDetail,
    AiLogInvestigationList,
    AiLogInvestigationListItem,
)
from context_router.services.workspace_containers import (
    ContainerLogRecord,
    WorkspaceContainerError,
    WorkspaceContainerService,
)

ERROR_PATTERN = re.compile(
    r"(?i)(?:\b(?:error|fatal|panic|exception|traceback|critical|unhandled)\b|"
    r"segmentation fault|connection refused|failed to|timed?\s*out|npm err!)"
)
CRITICAL_PATTERN = re.compile(r"(?i)\b(?:fatal|panic|critical|segmentation fault)\b")
EXCEPTION_NAME_PATTERN = re.compile(r"\b(?:[A-Za-z_][\w.]*)(?:Error|Exception|Failure|Timeout)\b")
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(\b(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"password|passwd|secret|cookie)\b\s*[:=]\s*)([^\s,;]+|\"[^\"]*\")"
)
BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
URL_CREDENTIAL_PATTERN = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^\s:/]+:)([^@\s]+)(@)")
UUID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b")
LONG_HEX_PATTERN = re.compile(r"\b[0-9a-fA-F]{16,}\b")
NUMBER_PATTERN = re.compile(r"\b\d+\b")
MAX_EXCERPT_LINES = 160
MAX_EXCERPT_CHARS = 64_000


class AiLogVisualizationError(RuntimeError):
    def __init__(self, message: str, *, code: str = "log_visualization_failed") -> None:
        super().__init__(message)
        self.code = code


class AiLogVisualizationService:
    def __init__(
        self,
        *,
        records: AiLogInvestigationStore,
        tasks: TaskStore,
        projects: ProjectStore,
        workspaces: WorkspaceStore,
        containers: WorkspaceContainerService,
    ) -> None:
        self._records = records
        self._tasks = tasks
        self._projects = projects
        self._workspaces = workspaces
        self._containers = containers

    def list_task_containers(
        self,
        *,
        task_id: int,
        query: str | None = None,
    ) -> dict[str, object]:
        task, workspace_id = self._task_scope(task_id)
        projects = self._workspace_projects(workspace_id)
        try:
            containers = self._containers.list_containers(
                workspace_id,
                project_names={project.id: project.name for project in projects},
                project_kinds={project.id: project.project_kind for project in projects},
            )
        except WorkspaceContainerError as exc:
            raise AiLogVisualizationError(str(exc), code="container_logs_unavailable") from exc
        keyword = (query or "").strip().casefold()
        if keyword:
            containers = [
                item
                for item in containers
                if keyword
                in " ".join(
                    value
                    for value in (item.name, item.image, item.project_name, item.project_kind)
                    if value
                ).casefold()
            ]
        return {
            "task_id": task_id,
            "workspace_id": workspace_id,
            "workspace_name": task.workspace_name,
            "environment": task.database_environment or "local",
            "containers": [container.model_dump(exclude_none=True) for container in containers],
            "returned_count": len(containers),
        }

    def inspect_container_errors(
        self,
        *,
        task_id: int,
        container_id: str,
        since_minutes: int = 15,
        tail: int = 500,
        keywords: list[str] | None = None,
    ) -> dict[str, object]:
        task, workspace_id = self._task_scope(task_id)
        projects = self._workspace_projects(workspace_id)
        project_names = {project.id: project.name for project in projects}
        project_kinds = {project.id: project.project_kind for project in projects}
        try:
            registered = self._containers.list_containers(
                workspace_id,
                project_names=project_names,
                project_kinds=project_kinds,
            )
        except WorkspaceContainerError as exc:
            raise AiLogVisualizationError(str(exc), code="container_logs_unavailable") from exc
        container = next((item for item in registered if item.id == container_id), None)
        if container is None:
            raise AiLogVisualizationError(
                "容器未在当前 Agent Context Router 工作空间注册",
                code="container_not_registered",
            )

        since = (
            (datetime.now(UTC) - timedelta(minutes=since_minutes))
            .isoformat()
            .replace("+00:00", "Z")
        )
        try:
            snapshot = self._containers.read_log_snapshot(
                workspace_id,
                container_id,
                tail=tail,
                since=since,
            )
        except WorkspaceContainerError as exc:
            raise AiLogVisualizationError(str(exc), code="container_logs_unavailable") from exc

        extracted = _extract_errors(snapshot.records, keywords or [])
        if extracted is None:
            return {
                "status": "no_errors",
                "record_created": False,
                "task_id": task_id,
                "workspace_id": workspace_id,
                "container_id": container.id,
                "container_name": container.name,
                "scanned_line_count": len(snapshot.records),
                "truncated": snapshot.truncated,
                "message": "本次有界日志中未识别到错误，因此没有生成日志可视化记录",
            }

        now = datetime.now(UTC)
        fingerprint = hashlib.sha256(
            f"{workspace_id}\n{container.id}\n{_normalize_signature(extracted['anchor'])}".encode()
        ).hexdigest()
        idempotency_key = hashlib.sha256(f"{task_id}:{fingerprint}".encode()).hexdigest()
        workspace_name = task.workspace_name or self._workspace_name(workspace_id)
        record = AiLogInvestigationRecord(
            id=str(uuid4()),
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            task_id=task_id,
            source=task.agent_name or "agent",
            description=task.task,
            environment=task.database_environment or "local",
            container_id=container.id,
            container_name=container.name,
            image=container.image,
            project_id=container.project_id,
            project_name=container.project_name,
            project_kind=container.project_kind,
            severity=str(extracted["severity"]),
            error_title=str(extracted["title"]),
            error_excerpt=str(extracted["excerpt"]),
            occurred_at=extracted["occurred_at"],  # type: ignore[arg-type]
            occurrence_count=int(extracted["occurrence_count"]),
            log_line_count=len(snapshot.records),
            truncated=snapshot.truncated or bool(extracted["truncated"]),
            fingerprint=fingerprint,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )
        try:
            stored = self._records.upsert(record)
        except AiLogInvestigationRepositoryError as exc:
            raise AiLogVisualizationError(str(exc)) from exc
        return {
            "status": "recorded",
            "record_created": True,
            "record": self._detail(stored).model_dump(mode="json"),
        }

    def list_records(
        self,
        *,
        workspace_id: str | None,
        severity: str | None,
        limit: int,
        offset: int,
    ) -> AiLogInvestigationList:
        try:
            records = self._records.list_records(
                workspace_id=workspace_id,
                severity=severity,
                limit=limit + 1,
                offset=offset,
            )
        except AiLogInvestigationRepositoryError as exc:
            raise AiLogVisualizationError(str(exc)) from exc
        return AiLogInvestigationList(
            items=[self._item(record) for record in records[:limit]],
            limit=limit,
            offset=offset,
            has_more=len(records) > limit,
        )

    def get_record(self, record_id: str) -> AiLogInvestigationDetail:
        try:
            record = self._records.get(record_id)
        except AiLogInvestigationRepositoryError as exc:
            raise AiLogVisualizationError(str(exc)) from exc
        if record is None:
            raise AiLogVisualizationError("日志排查记录不存在", code="record_not_found")
        return self._detail(record)

    def _task_scope(self, task_id: int):
        try:
            task = self._tasks.get_task(task_id)
        except TaskRepositoryError as exc:
            raise AiLogVisualizationError(str(exc), code="task_not_found") from exc
        workspace_id = task.workspace_id
        if workspace_id is None and task.project_id is not None:
            try:
                workspace_id = self._projects.get_project(task.project_id).workspace_id
            except ProjectRepositoryError as exc:
                raise AiLogVisualizationError(str(exc), code="task_not_found") from exc
        if workspace_id is None:
            raise AiLogVisualizationError("任务没有关联工作空间", code="task_not_found")
        return task, workspace_id

    def _workspace_projects(self, workspace_id: str):
        try:
            return self._projects.list_projects(workspace_id)
        except ProjectRepositoryError as exc:
            raise AiLogVisualizationError(str(exc), code="workspace_not_found") from exc

    def _workspace_name(self, workspace_id: str) -> str:
        try:
            return self._workspaces.get_workspace(workspace_id).name
        except WorkspaceRepositoryError as exc:
            raise AiLogVisualizationError(str(exc), code="workspace_not_found") from exc

    @staticmethod
    def _item(record: AiLogInvestigationRecord) -> AiLogInvestigationListItem:
        return AiLogInvestigationListItem(
            id=record.id,
            workspace_id=record.workspace_id,
            workspace_name=record.workspace_name,
            source=record.source,
            description=record.description,
            environment=record.environment,
            container_id=record.container_id,
            container_name=record.container_name,
            image=record.image,
            project_id=record.project_id,
            project_name=record.project_name,
            project_kind=record.project_kind,
            severity=record.severity,
            error_title=record.error_title,
            occurred_at=record.occurred_at,
            occurrence_count=record.occurrence_count,
            truncated=record.truncated,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @classmethod
    def _detail(cls, record: AiLogInvestigationRecord) -> AiLogInvestigationDetail:
        return AiLogInvestigationDetail(
            **cls._item(record).model_dump(),
            task_id=record.task_id,
            error_excerpt=record.error_excerpt,
            log_line_count=record.log_line_count,
            fingerprint=record.fingerprint,
        )


def _extract_errors(
    records: list[ContainerLogRecord],
    keywords: list[str],
) -> dict[str, object] | None:
    anchors = [
        index for index, record in enumerate(records) if ERROR_PATTERN.search(record.content)
    ]
    if not anchors:
        return None
    normalized_keywords = [keyword.strip().casefold() for keyword in keywords if keyword.strip()]
    if normalized_keywords:
        matched = [
            index
            for index in anchors
            if any(
                keyword
                in "\n".join(
                    item.content for item in records[max(0, index - 2) : index + 6]
                ).casefold()
                for keyword in normalized_keywords
            )
        ]
        if matched:
            anchors = matched

    ranges: list[tuple[int, int]] = []
    for index in anchors:
        start, end = max(0, index - 2), min(len(records), index + 15)
        if ranges and start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    selected_indices = [index for start, end in ranges for index in range(start, end)]
    selected_indices = selected_indices[-MAX_EXCERPT_LINES:]
    lines = [_format_record(records[index]) for index in selected_indices]
    excerpt = _redact("\n".join(lines))
    excerpt_truncated = len(excerpt) > MAX_EXCERPT_CHARS
    if excerpt_truncated:
        excerpt = excerpt[-MAX_EXCERPT_CHARS:]
        excerpt = f"[较早的错误上下文已截断]\n{excerpt}"

    latest = records[anchors[-1]]
    title_record = next(
        (
            records[index]
            for index in reversed(anchors)
            if EXCEPTION_NAME_PATTERN.search(records[index].content)
        ),
        latest,
    )
    title_match = EXCEPTION_NAME_PATTERN.search(title_record.content)
    title = title_match.group(0) if title_match else title_record.content.strip()
    title = _redact(title)[:240] or "Docker 容器错误"
    occurred_at = _parse_timestamp(latest.timestamp)
    severity = (
        "critical"
        if any(CRITICAL_PATTERN.search(records[index].content) for index in anchors)
        else "error"
    )
    return {
        "anchor": title_record.content,
        "title": title,
        "severity": severity,
        "excerpt": excerpt,
        "occurred_at": occurred_at,
        "occurrence_count": len(anchors),
        "truncated": excerpt_truncated or len(selected_indices) >= MAX_EXCERPT_LINES,
    }


def _format_record(record: ContainerLogRecord) -> str:
    timestamp = record.timestamp or "无时间戳"
    return f"[{timestamp}] [{record.stream}] {record.content}"


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _redact(value: str) -> str:
    value = BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    value = SENSITIVE_KEY_PATTERN.sub(lambda match: f"{match.group(1)}[REDACTED]", value)
    return URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]\3", value)


def _normalize_signature(value: str) -> str:
    value = UUID_PATTERN.sub("<uuid>", value.casefold())
    value = LONG_HEX_PATTERN.sub("<hex>", value)
    value = NUMBER_PATTERN.sub("<n>", value)
    return " ".join(value.split())[:1000]
