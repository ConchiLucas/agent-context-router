from __future__ import annotations

from pathlib import Path

from context_router.repositories.document_read_repository import (
    DocumentReadItemWrite,
    DocumentReadRepositoryError,
    DocumentReadStore,
)
from context_router.repositories.task_repository import TaskReader, TaskRepositoryError
from context_router.schemas.context import (
    ContextDocumentReadItem,
    ContextDocumentReadItemError,
    ContextDocumentReadRequest,
    ReadContextDocumentResult,
)
from context_router.services.document_tree import CachedDocument, DocumentCache
from context_router.services.markdown_section import (
    MarkdownSectionError,
    extract_markdown_section,
)
from context_router.services.mcp_trace import current_tool_call_id
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError

MAX_READ_REQUESTS = 10
MAX_DOCUMENT_CHARACTERS = 200_000
MAX_RESPONSE_CHARACTERS = 400_000


class ContextDocumentReadError(ValueError):
    pass


class ContextDocumentReadService:
    def __init__(
        self,
        registry: ProjectRegistry,
        task_repository: TaskReader,
        read_repository: DocumentReadStore,
    ) -> None:
        self._registry = registry
        self._task_repository = task_repository
        self._read_repository = read_repository

    def read(
        self,
        *,
        task_id: int,
        requests: list[ContextDocumentReadRequest],
    ) -> ReadContextDocumentResult:
        if task_id < 1:
            raise ContextDocumentReadError("task_id 必须是正整数")
        if not requests:
            raise ContextDocumentReadError("requests 至少需要一个文档")
        if len(requests) > MAX_READ_REQUESTS:
            raise ContextDocumentReadError(f"requests 不能超过 {MAX_READ_REQUESTS} 个文档或章节")

        try:
            task = self._task_repository.get_task(task_id)
        except TaskRepositoryError as exc:
            raise ContextDocumentReadError(str(exc)) from exc

        try:
            project = self._registry.get_snapshot_by_project_key(task.project_key)
        except ProjectRegistryError as exc:
            raise ContextDocumentReadError("任务绑定的项目当前不可用，请重新 prepare") from exc

        results: list[ContextDocumentReadItem] = []
        writes: list[DocumentReadItemWrite] = []
        response_characters = 0

        for position, request in enumerate(requests, start=1):
            result, write = self._resolve_request(
                position=position,
                request=request,
                cache=project.cache,
                response_characters=response_characters,
            )
            results.append(result)
            writes.append(write)
            if result.content is not None:
                response_characters += len(result.content)

        try:
            trace_call_id = current_tool_call_id()
            if trace_call_id is None:
                read_call_id = self._read_repository.create_read_call(
                    task_id=task_id,
                    items=writes,
                )
            else:
                read_call_id = self._read_repository.create_read_call(
                    task_id=task_id,
                    items=writes,
                    tool_call_id=trace_call_id,
                )
        except DocumentReadRepositoryError as exc:
            raise ContextDocumentReadError(str(exc)) from exc

        return ReadContextDocumentResult(
            task_id=task_id,
            read_call_id=read_call_id,
            documents=results,
        )

    def _resolve_request(
        self,
        *,
        position: int,
        request: ContextDocumentReadRequest,
        cache: DocumentCache,
        response_characters: int,
    ) -> tuple[ContextDocumentReadItem, DocumentReadItemWrite]:
        document = cache.documents.get(request.document_id)
        if document is None:
            return self._error_item(
                position=position,
                request=request,
                code="document_not_found",
                message="文档不在当前任务项目的映射中",
            )

        path = self._relative_path(document, cache)
        section = request.section.strip() if request.section is not None else None
        if request.section is not None and not section:
            return self._error_item(
                position=position,
                request=request,
                code="invalid_section",
                message="section 不能为空",
                path=path,
            )

        if document.error and not document.content:
            return self._error_item(
                position=position,
                request=request,
                code="document_unavailable",
                message="文档当前无法读取",
                path=path,
            )

        try:
            content = (
                extract_markdown_section(document.content, section)
                if section is not None
                else document.content
            )
        except MarkdownSectionError as exc:
            return self._error_item(
                position=position,
                request=request,
                code=exc.code,
                message=str(exc),
                path=path,
            )

        if len(content) > MAX_DOCUMENT_CHARACTERS:
            return self._error_item(
                position=position,
                request=request,
                code="document_too_large",
                message="文档内容过大，请指定 section 读取",
                path=path,
            )
        if response_characters + len(content) > MAX_RESPONSE_CHARACTERS:
            return self._error_item(
                position=position,
                request=request,
                code="response_too_large",
                message="本次返回内容过大，请拆分调用或指定 section",
                path=path,
            )

        result = ContextDocumentReadItem(
            position=position,
            document_id=request.document_id,
            path=path,
            title=document.title,
            section=section,
            content=content,
        )
        write = DocumentReadItemWrite(
            position=position,
            document_id=request.document_id,
            document_path=path,
            requested_section=section,
            status="ok",
        )
        return result, write

    @staticmethod
    def _error_item(
        *,
        position: int,
        request: ContextDocumentReadRequest,
        code: str,
        message: str,
        path: str | None = None,
    ) -> tuple[ContextDocumentReadItem, DocumentReadItemWrite]:
        section = request.section.strip() if request.section else None
        result = ContextDocumentReadItem(
            position=position,
            document_id=request.document_id,
            path=path,
            section=section,
            error=ContextDocumentReadItemError(code=code, message=message),
        )
        write = DocumentReadItemWrite(
            position=position,
            document_id=request.document_id,
            document_path=path,
            requested_section=section,
            status="error",
            error_code=code,
        )
        return result, write

    @staticmethod
    def _relative_path(document: CachedDocument, cache: DocumentCache) -> str:
        try:
            return Path(document.path).resolve().relative_to(cache.project_root).as_posix()
        except ValueError:
            if document.relative_path:
                return document.relative_path.removeprefix("./")
            return "AGENTS.md"
