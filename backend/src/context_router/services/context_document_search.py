from __future__ import annotations

from dataclasses import dataclass, field

from context_router.repositories.document_search_repository import (
    DocumentSearchHit,
    DocumentSearchRepositoryError,
    DocumentSearchStore,
)
from context_router.repositories.task_repository import TaskReader, TaskRepositoryError
from context_router.schemas.context import (
    ContextDocumentSearchResultItem,
    ContextDocumentSearchSection,
    SearchContextDocumentsResult,
)
from context_router.services.document_search_index import (
    DOCUMENT_SEARCH_INDEX_FORMAT_VERSION,
)
from context_router.services.markdown_search_parser import normalize_search_text
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError

MAX_SEARCH_QUERY_CHARACTERS = 200
MAX_SEARCH_RESULTS = 50
MAX_MATCHED_SECTIONS = 5
MAX_CANDIDATE_HITS = 250


class ContextDocumentSearchError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class _AggregatedDocument:
    document_id: str
    path: str
    title: str | None
    summary: str | None
    relevance: float
    matched_sections: list[ContextDocumentSearchSection] = field(default_factory=list)
    match_reasons: list[str] = field(default_factory=list)
    _section_keys: set[tuple[str | None, tuple[str, ...], bool]] = field(default_factory=set)

    def add_hit(self, hit: DocumentSearchHit) -> None:
        self.relevance = max(self.relevance, hit.relevance)
        section_key = (hit.section, hit.section_path, hit.section_readable)
        if (
            section_key not in self._section_keys
            and len(self.matched_sections) < MAX_MATCHED_SECTIONS
        ):
            self._section_keys.add(section_key)
            self.matched_sections.append(
                ContextDocumentSearchSection(
                    section=hit.section,
                    section_path=list(hit.section_path),
                    can_read_section=hit.section_readable,
                )
            )
        for reason in hit.match_reasons:
            if reason not in self.match_reasons:
                self.match_reasons.append(reason)

    def to_result(self) -> ContextDocumentSearchResultItem:
        return ContextDocumentSearchResultItem(
            document_id=self.document_id,
            path=self.path,
            title=self.title,
            summary=self.summary,
            relevance=min(max(round(self.relevance, 6), 0.0), 1.0),
            matched_sections=self.matched_sections,
            match_reasons=self.match_reasons,
        )


class ContextDocumentSearchService:
    def __init__(
        self,
        registry: ProjectRegistry,
        task_repository: TaskReader,
        search_repository: DocumentSearchStore,
    ) -> None:
        self._registry = registry
        self._task_repository = task_repository
        self._search_repository = search_repository

    def search(
        self,
        *,
        task_id: int,
        query: str,
        limit: int = 10,
    ) -> SearchContextDocumentsResult:
        normalized_query = self._validate_input(task_id=task_id, query=query, limit=limit)
        try:
            task = self._task_repository.get_task(task_id)
        except TaskRepositoryError as exc:
            raise ContextDocumentSearchError(
                str(exc),
                code="task_not_found"
                if str(exc) == "任务不存在"
                else "document_search_unavailable",
            ) from exc

        try:
            project = self._registry.get_snapshot_for_task(
                project_id=task.project_id,
                project_key=task.project_key,
            )
        except ProjectRegistryError as exc:
            raise ContextDocumentSearchError(
                "任务绑定的项目当前不可用，请重新 prepare",
                code="task_project_unavailable",
            ) from exc

        try:
            state = self._search_repository.get_index_state(project.id)
        except DocumentSearchRepositoryError as exc:
            raise ContextDocumentSearchError(
                "文档检索服务暂时不可用",
                code="document_search_unavailable",
            ) from exc

        if (
            state is None
            or state.index_version != project.cache.version
            or state.index_format_version != DOCUMENT_SEARCH_INDEX_FORMAT_VERSION
        ):
            raise ContextDocumentSearchError(
                "当前项目的文档检索索引尚未就绪，请刷新项目映射后重试",
                code="document_search_index_not_ready",
            )

        candidate_limit = min(limit * 5, MAX_CANDIDATE_HITS)
        try:
            hits = self._search_repository.search(
                project_id=project.id,
                index_version=project.cache.version,
                query=normalized_query,
                limit=candidate_limit,
            )
        except DocumentSearchRepositoryError as exc:
            raise ContextDocumentSearchError(
                "文档检索失败",
                code="document_search_failed",
            ) from exc

        documents: dict[str, _AggregatedDocument] = {}
        for hit in hits:
            aggregate = documents.get(hit.document_id)
            if aggregate is None:
                aggregate = _AggregatedDocument(
                    document_id=hit.document_id,
                    path=hit.path,
                    title=hit.title,
                    summary=hit.summary,
                    relevance=hit.relevance,
                )
                documents[hit.document_id] = aggregate
            aggregate.add_hit(hit)

        ordered = sorted(
            documents.values(),
            key=lambda item: (-item.relevance, item.path, item.document_id),
        )
        results = [item.to_result() for item in ordered[:limit]]
        return SearchContextDocumentsResult(
            task_id=task_id,
            query=normalized_query,
            returned_count=len(results),
            truncated=len(ordered) > limit or len(hits) >= candidate_limit,
            results=results,
        )

    @staticmethod
    def _validate_input(*, task_id: int, query: str, limit: int) -> str:
        if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id < 1:
            raise ContextDocumentSearchError(
                "task_id 必须是正整数",
                code="invalid_task_id",
            )
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_SEARCH_RESULTS
        ):
            raise ContextDocumentSearchError(
                f"limit 必须在 1 到 {MAX_SEARCH_RESULTS} 之间",
                code="invalid_search_limit",
            )
        if not isinstance(query, str):
            raise ContextDocumentSearchError(
                "query 格式不正确",
                code="invalid_search_query",
            )
        normalized_query = normalize_search_text(query)
        if not normalized_query:
            raise ContextDocumentSearchError(
                "query 不能为空",
                code="invalid_search_query",
            )
        if len(normalized_query) > MAX_SEARCH_QUERY_CHARACTERS:
            raise ContextDocumentSearchError(
                f"query 不能超过 {MAX_SEARCH_QUERY_CHARACTERS} 个字符",
                code="invalid_search_query",
            )
        return normalized_query
