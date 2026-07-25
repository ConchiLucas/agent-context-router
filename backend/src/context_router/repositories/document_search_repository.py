from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol, cast

import psycopg

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_TOKEN_PATTERN = re.compile(r"[0-9a-z_./:-]+|[\u3400-\u9fff]+")
_MAX_SEARCH_CANDIDATES = 250
_TRIGRAM_THRESHOLD = 0.25


class DocumentSearchRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DocumentSearchChunkWrite:
    document_id: str
    path: str
    title: str | None
    summary: str | None
    section: str | None
    section_path: tuple[str, ...]
    section_ordinal: int
    section_readable: bool
    chunk_index: int
    body_text: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class DocumentSearchIndexState:
    project_id: str
    index_version: str
    index_format_version: int
    document_count: int
    chunk_count: int
    indexed_at: datetime


@dataclass(frozen=True, slots=True)
class DocumentSearchHit:
    document_id: str
    path: str
    title: str | None
    summary: str | None
    section: str | None
    section_path: tuple[str, ...]
    section_readable: bool
    relevance: float
    match_reasons: tuple[str, ...]


class DocumentSearchStore(Protocol):
    def replace_project_index(
        self,
        *,
        project_id: str,
        index_version: str,
        index_format_version: int,
        chunks: Sequence[DocumentSearchChunkWrite],
    ) -> DocumentSearchIndexState: ...

    def get_index_state(self, project_id: str) -> DocumentSearchIndexState | None: ...

    def search(
        self,
        *,
        project_id: str,
        index_version: str,
        query: str,
        limit: int,
    ) -> list[DocumentSearchHit]: ...


class InMemoryDocumentSearchRepository:
    def __init__(self) -> None:
        self._states: dict[str, DocumentSearchIndexState] = {}
        self._chunks: dict[str, tuple[str, tuple[DocumentSearchChunkWrite, ...]]] = {}
        self._lock = RLock()

    def replace_project_index(
        self,
        *,
        project_id: str,
        index_version: str,
        index_format_version: int,
        chunks: Sequence[DocumentSearchChunkWrite],
    ) -> DocumentSearchIndexState:
        safe_chunks = _validate_replacement(
            project_id=project_id,
            index_version=index_version,
            index_format_version=index_format_version,
            chunks=chunks,
        )
        state = DocumentSearchIndexState(
            project_id=project_id,
            index_version=index_version,
            index_format_version=index_format_version,
            document_count=len({chunk.document_id for chunk in safe_chunks}),
            chunk_count=len(safe_chunks),
            indexed_at=datetime.now(UTC),
        )
        with self._lock:
            self._chunks[project_id] = (index_version, safe_chunks)
            self._states[project_id] = state
        return state

    def get_index_state(self, project_id: str) -> DocumentSearchIndexState | None:
        _validate_project_id(project_id)
        with self._lock:
            return self._states.get(project_id)

    def search(
        self,
        *,
        project_id: str,
        index_version: str,
        query: str,
        limit: int,
    ) -> list[DocumentSearchHit]:
        _validate_project_id(project_id)
        _validate_sha256(index_version, "索引版本")
        normalized_query = _normalize_query(query)
        safe_limit = _validate_search_limit(limit)
        with self._lock:
            current = self._chunks.get(project_id)
            if current is None or current[0] != index_version:
                return []
            chunks = current[1]

        scored = [
            result
            for chunk in chunks
            if (result := _score_in_memory_chunk(chunk, normalized_query)) is not None
        ]
        scored.sort(
            key=lambda item: (
                -item[0].relevance,
                item[0].path,
                item[0].document_id,
                item[1],
                item[2],
            )
        )
        return [item[0] for item in scored[:safe_limit]]


class PostgresDocumentSearchRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def replace_project_index(
        self,
        *,
        project_id: str,
        index_version: str,
        index_format_version: int,
        chunks: Sequence[DocumentSearchChunkWrite],
    ) -> DocumentSearchIndexState:
        safe_chunks = _validate_replacement(
            project_id=project_id,
            index_version=index_version,
            index_format_version=index_format_version,
            chunks=chunks,
        )
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
                connection.execute(
                    "DELETE FROM document_search_chunks WHERE project_id = %s",
                    (project_id,),
                )
                if safe_chunks:
                    with connection.cursor() as cursor:
                        cursor.executemany(
                            _INSERT_CHUNK,
                            [
                                _chunk_insert_parameters(
                                    project_id=project_id,
                                    index_version=index_version,
                                    chunk=chunk,
                                )
                                for chunk in safe_chunks
                            ],
                        )
                row = connection.execute(
                    """
                    INSERT INTO document_search_index_states (
                        project_id,
                        index_version,
                        index_format_version,
                        document_count,
                        chunk_count,
                        indexed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (project_id) DO UPDATE
                    SET
                        index_version = EXCLUDED.index_version,
                        index_format_version = EXCLUDED.index_format_version,
                        document_count = EXCLUDED.document_count,
                        chunk_count = EXCLUDED.chunk_count,
                        indexed_at = CURRENT_TIMESTAMP
                    RETURNING
                        project_id,
                        index_version,
                        index_format_version,
                        document_count,
                        chunk_count,
                        indexed_at
                    """,
                    (
                        project_id,
                        index_version,
                        index_format_version,
                        len({chunk.document_id for chunk in safe_chunks}),
                        len(safe_chunks),
                    ),
                ).fetchone()
        except psycopg.errors.ForeignKeyViolation as exc:
            raise DocumentSearchRepositoryError("文档搜索索引对应的项目不存在") from exc
        except psycopg.Error as exc:
            raise DocumentSearchRepositoryError("文档搜索索引替换失败") from exc

        if row is None:
            raise DocumentSearchRepositoryError("文档搜索索引替换后没有返回索引状态")
        return _state_from_row(row)

    def get_index_state(self, project_id: str) -> DocumentSearchIndexState | None:
        _validate_project_id(project_id)
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
                row = connection.execute(
                    """
                    SELECT
                        project_id,
                        index_version,
                        index_format_version,
                        document_count,
                        chunk_count,
                        indexed_at
                    FROM document_search_index_states
                    WHERE project_id = %s
                    """,
                    (project_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise DocumentSearchRepositoryError("文档搜索索引状态读取失败") from exc
        return _state_from_row(row) if row is not None else None

    def search(
        self,
        *,
        project_id: str,
        index_version: str,
        query: str,
        limit: int,
    ) -> list[DocumentSearchHit]:
        _validate_project_id(project_id)
        _validate_sha256(index_version, "索引版本")
        normalized_query = _normalize_query(query)
        safe_limit = _validate_search_limit(limit)
        trigram_enabled = len(normalized_query) >= 3
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
                # The `%>` operator is backed by gin_trgm_ops and evaluates
                # word_similarity(query, indexed_text). Keep the threshold local
                # to this transaction so concurrent connections are unaffected.
                connection.execute(
                    "SELECT set_config('pg_trgm.word_similarity_threshold', %s, true)",
                    (str(_TRIGRAM_THRESHOLD),),
                )
                rows = connection.execute(
                    _SEARCH_CHUNKS,
                    _search_parameters(
                        normalized_query=normalized_query,
                        trigram_enabled=trigram_enabled,
                        project_id=project_id,
                        index_version=index_version,
                        limit=safe_limit,
                    ),
                ).fetchall()
        except psycopg.Error as exc:
            raise DocumentSearchRepositoryError("文档搜索失败") from exc
        return [_hit_from_row(row) for row in rows]

    def _require_database_url(self) -> str:
        if not self._database_url:
            raise DocumentSearchRepositoryError("任务数据库尚未配置")
        return self._database_url


def _validate_replacement(
    *,
    project_id: str,
    index_version: str,
    index_format_version: int,
    chunks: Sequence[DocumentSearchChunkWrite],
) -> tuple[DocumentSearchChunkWrite, ...]:
    _validate_project_id(project_id)
    _validate_sha256(index_version, "索引版本")
    if isinstance(index_format_version, bool) or index_format_version < 1:
        raise DocumentSearchRepositoryError("索引格式版本必须大于 0")

    safe_chunks = tuple(chunks)
    positions: set[tuple[str, int, int]] = set()
    for chunk in safe_chunks:
        _validate_chunk(chunk)
        position = (chunk.document_id, chunk.section_ordinal, chunk.chunk_index)
        if position in positions:
            raise DocumentSearchRepositoryError("文档搜索分块位置不能重复")
        positions.add(position)
    return safe_chunks


def _validate_chunk(chunk: DocumentSearchChunkWrite) -> None:
    _validate_text(chunk.document_id, "文档 ID", 64, required=True)
    _validate_text(chunk.path, "文档路径", 4_096, required=True)
    _validate_text(chunk.title, "文档标题", 2_000)
    _validate_text(chunk.summary, "文档概要", 20_000)
    _validate_text(chunk.section, "章节标题", 2_000)
    if len(chunk.section_path) > 32:
        raise DocumentSearchRepositoryError("章节路径层级不能超过 32")
    for item in chunk.section_path:
        _validate_text(item, "章节路径", 2_000, required=True)
    if isinstance(chunk.section_ordinal, bool) or chunk.section_ordinal < 0:
        raise DocumentSearchRepositoryError("章节顺序不能小于 0")
    if isinstance(chunk.chunk_index, bool) or chunk.chunk_index < 0:
        raise DocumentSearchRepositoryError("章节分块顺序不能小于 0")
    if not isinstance(chunk.body_text, str):
        raise DocumentSearchRepositoryError("文档分块正文格式不正确")
    _validate_sha256(chunk.content_hash, "分块内容摘要")


def _validate_project_id(project_id: str) -> None:
    _validate_text(project_id, "项目 ID", 32, required=True)


def _validate_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise DocumentSearchRepositoryError(f"{label}必须是 64 位小写 SHA-256")


def _validate_text(
    value: str | None,
    label: str,
    max_length: int,
    *,
    required: bool = False,
) -> None:
    if required and (not isinstance(value, str) or not value.strip()):
        raise DocumentSearchRepositoryError(f"{label}不能为空")
    if value is not None and not isinstance(value, str):
        raise DocumentSearchRepositoryError(f"{label}格式不正确")
    if value is not None and len(value) > max_length:
        raise DocumentSearchRepositoryError(f"{label}长度不能超过 {max_length}")


def _normalize_query(query: str) -> str:
    if not isinstance(query, str):
        raise DocumentSearchRepositoryError("搜索关键词格式不正确")
    normalized = unicodedata.normalize("NFKC", query).strip().lower()
    if not normalized:
        raise DocumentSearchRepositoryError("搜索关键词不能为空")
    if len(normalized) > 200:
        raise DocumentSearchRepositoryError("搜索关键词长度不能超过 200")
    return normalized


def _validate_search_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 250:
        raise DocumentSearchRepositoryError(
            f"搜索候选数量必须在 1 到 {_MAX_SEARCH_CANDIDATES} 之间"
        )
    return limit


def _search_parameters(
    *,
    normalized_query: str,
    trigram_enabled: bool,
    project_id: str,
    index_version: str,
    limit: int,
) -> tuple[object, ...]:
    return (
        normalized_query,
        normalized_query,
        trigram_enabled,
        _TRIGRAM_THRESHOLD,
        project_id,
        index_version,
        limit,
    )


def _chunk_insert_parameters(
    *,
    project_id: str,
    index_version: str,
    chunk: DocumentSearchChunkWrite,
) -> tuple[object, ...]:
    search_text = _combined_search_text(chunk)
    return (
        project_id,
        index_version,
        chunk.document_id,
        chunk.path,
        chunk.title,
        chunk.summary,
        chunk.section,
        list(chunk.section_path),
        chunk.section_ordinal,
        chunk.section_readable,
        chunk.chunk_index,
        chunk.body_text,
        search_text,
        chunk.title,
        chunk.section,
        chunk.path,
        chunk.summary,
        chunk.body_text,
        chunk.content_hash,
    )


def _combined_search_text(chunk: DocumentSearchChunkWrite) -> str:
    return "\n".join(
        _normalize_text(value)
        for value in (
            chunk.path,
            chunk.title,
            chunk.summary,
            chunk.section,
            chunk.body_text,
        )
        if value
    )


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).lower()


def _score_in_memory_chunk(
    chunk: DocumentSearchChunkWrite,
    query: str,
) -> tuple[DocumentSearchHit, int, int] | None:
    fields = (
        ("title", chunk.title, 1.00),
        ("path", chunk.path, 0.90),
        ("summary", chunk.summary, 0.85),
        ("section", chunk.section, 0.95),
        ("body", chunk.body_text, 0.65),
    )
    normalized_fields = [
        (name, _normalize_text(value), weight)
        for name, value, weight in fields
        if value is not None
    ]
    trigram_enabled = len(query) >= 3
    query_tokens = _tokens(query)
    reasons: list[str] = []
    exact_scores: list[float] = []
    fts_scores: list[float] = []
    fuzzy_scores: list[float] = []
    matched_fields = 0

    for name, value, weight in normalized_fields:
        exact = query in value
        full_text = bool(query_tokens) and query_tokens.issubset(_tokens(value))
        fuzzy = _word_similarity(query, value) if trigram_enabled else 0.0
        if exact:
            reasons.append(f"{name}_exact")
            exact_scores.append(_exact_score(name, query == value))
        elif full_text:
            reasons.append(f"{name}_full_text")
        elif fuzzy >= _TRIGRAM_THRESHOLD:
            reasons.append(f"{name}_fuzzy")
        else:
            continue

        matched_fields += 1
        if full_text:
            fts_scores.append(weight)
        if fuzzy >= _TRIGRAM_THRESHOLD:
            fuzzy_scores.append(fuzzy * weight)

    if not reasons:
        return None

    fts_score = max(fts_scores, default=0.0)
    fuzzy_score = max(fuzzy_scores, default=0.0)
    rank_score = (0.60 * fts_score) + (0.40 * fuzzy_score)
    bonus = min(0.04, max(0, matched_fields - 1) * 0.01)
    relevance = round(min(1.0, max(max(exact_scores, default=0.0), rank_score) + bonus), 4)
    return (
        DocumentSearchHit(
            document_id=chunk.document_id,
            path=chunk.path,
            title=chunk.title,
            summary=chunk.summary,
            section=chunk.section,
            section_path=tuple(chunk.section_path),
            section_readable=chunk.section_readable,
            relevance=relevance,
            match_reasons=tuple(reasons),
        ),
        chunk.section_ordinal,
        chunk.chunk_index,
    )


def _exact_score(field: str, equal: bool) -> float:
    if field == "title":
        return 1.00 if equal else 0.98
    return {
        "section": 0.95,
        "path": 0.92,
        "summary": 0.88,
        "body": 0.75,
    }[field]


def _tokens(value: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(value))


def _word_similarity(query: str, value: str) -> float:
    if not value:
        return 0.0
    query_trigrams = _trigrams(query)
    words = _TOKEN_PATTERN.findall(value)
    candidates = [_trigram_similarity(query_trigrams, _trigrams(word)) for word in words]
    query_length = len(query)
    window = max(query_length + 4, 8)
    for offset in range(0, len(value), max(query_length // 2, 1)):
        candidates.append(
            _trigram_similarity(
                query_trigrams,
                _trigrams(value[offset : offset + window]),
            )
        )
    return max(candidates, default=0.0)


def _trigrams(value: str) -> set[str]:
    padded = f"  {value} "
    return {padded[index : index + 3] for index in range(len(padded) - 2)}


def _trigram_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return (2 * len(left & right)) / (len(left) + len(right))


def _state_from_row(row: tuple[object, ...]) -> DocumentSearchIndexState:
    return DocumentSearchIndexState(
        project_id=str(row[0]),
        index_version=str(row[1]),
        index_format_version=int(row[2]),
        document_count=int(row[3]),
        chunk_count=int(row[4]),
        indexed_at=cast(datetime, row[5]),
    )


def _hit_from_row(row: tuple[object, ...]) -> DocumentSearchHit:
    relevance = float(row[7])
    if not math.isfinite(relevance):
        relevance = 0.0
    return DocumentSearchHit(
        document_id=str(row[0]),
        path=str(row[1]),
        title=str(row[2]) if row[2] is not None else None,
        summary=str(row[3]) if row[3] is not None else None,
        section=str(row[4]) if row[4] is not None else None,
        section_path=tuple(str(item) for item in cast(Sequence[object], row[5])),
        section_readable=bool(row[6]),
        relevance=round(min(1.0, max(0.0, relevance)), 4),
        match_reasons=tuple(str(item) for item in cast(Sequence[object], row[8])),
    )


_INSERT_CHUNK = """
    INSERT INTO document_search_chunks (
        project_id,
        index_version,
        document_id,
        path,
        title,
        summary,
        section,
        section_path,
        section_ordinal,
        section_readable,
        chunk_index,
        body_text,
        search_text,
        search_vector,
        content_hash
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        setweight(to_tsvector('simple', COALESCE(%s, '')), 'A')
        || setweight(to_tsvector('simple', COALESCE(%s, '')), 'A')
        || setweight(to_tsvector('simple', COALESCE(%s, '')), 'B')
        || setweight(to_tsvector('simple', COALESCE(%s, '')), 'B')
        || setweight(to_tsvector('simple', COALESCE(%s, '')), 'D'),
        %s
    )
"""


_SEARCH_CHUNKS = """
    WITH search_input AS (
        SELECT
            %s::text AS query,
            websearch_to_tsquery('simple', %s::text) AS ts_query,
            %s::boolean AS trigram_enabled,
            %s::double precision AS trigram_threshold
    ),
    signals AS (
        SELECT
            chunk.*,
            input.query,
            input.ts_query,
            input.trigram_enabled,
            input.trigram_threshold,
            POSITION(input.query IN chunk.search_text) > 0 AS normalized_exact,
            POSITION(input.query IN LOWER(COALESCE(chunk.title, ''))) > 0
                AS title_exact,
            POSITION(input.query IN LOWER(chunk.path)) > 0 AS path_exact,
            POSITION(input.query IN LOWER(COALESCE(chunk.summary, ''))) > 0
                AS summary_exact,
            POSITION(input.query IN LOWER(COALESCE(chunk.section, ''))) > 0
                AS section_exact,
            POSITION(input.query IN LOWER(chunk.body_text)) > 0 AS body_exact,
            to_tsvector('simple', COALESCE(chunk.title, '')) @@ input.ts_query
                AS title_full_text,
            to_tsvector('simple', chunk.path) @@ input.ts_query AS path_full_text,
            to_tsvector('simple', COALESCE(chunk.summary, '')) @@ input.ts_query
                AS summary_full_text,
            to_tsvector('simple', COALESCE(chunk.section, '')) @@ input.ts_query
                AS section_full_text,
            to_tsvector('simple', chunk.body_text) @@ input.ts_query AS body_full_text,
            CASE WHEN input.trigram_enabled
                THEN word_similarity(input.query, LOWER(COALESCE(chunk.title, '')))
                ELSE 0.0 END AS title_fuzzy,
            CASE WHEN input.trigram_enabled
                THEN word_similarity(input.query, LOWER(chunk.path))
                ELSE 0.0 END AS path_fuzzy,
            CASE WHEN input.trigram_enabled
                THEN word_similarity(input.query, LOWER(COALESCE(chunk.summary, '')))
                ELSE 0.0 END AS summary_fuzzy,
            CASE WHEN input.trigram_enabled
                THEN word_similarity(input.query, LOWER(COALESCE(chunk.section, '')))
                ELSE 0.0 END AS section_fuzzy,
            CASE WHEN input.trigram_enabled
                THEN word_similarity(input.query, LOWER(chunk.body_text))
                ELSE 0.0 END AS body_fuzzy,
            ts_rank_cd(chunk.search_vector, input.ts_query, 32) AS full_text_rank
        FROM document_search_chunks AS chunk
        CROSS JOIN search_input AS input
        WHERE chunk.project_id = %s
          AND chunk.index_version = %s
          AND (
                chunk.search_vector @@ input.ts_query
                OR (
                    input.trigram_enabled
                    AND chunk.search_text %%> input.query
                )
                OR (
                    NOT input.trigram_enabled
                    AND POSITION(input.query IN chunk.search_text) > 0
                )
          )
    ),
    ranked AS (
        SELECT
            signals.*,
            GREATEST(
                CASE
                    WHEN title_exact AND LOWER(COALESCE(title, '')) = query THEN 1.00
                    WHEN title_exact THEN 0.98
                    ELSE 0.0
                END,
                CASE WHEN section_exact THEN 0.95 ELSE 0.0 END,
                CASE WHEN path_exact THEN 0.92 ELSE 0.0 END,
                CASE WHEN summary_exact THEN 0.88 ELSE 0.0 END,
                CASE WHEN body_exact THEN 0.75 ELSE 0.0 END,
                CASE WHEN normalized_exact THEN 0.70 ELSE 0.0 END
            ) AS exact_score,
            GREATEST(
                title_fuzzy * 1.00,
                section_fuzzy * 0.95,
                path_fuzzy * 0.90,
                summary_fuzzy * 0.85,
                body_fuzzy * 0.65
            ) AS fuzzy_score,
            (
                (title_exact OR title_full_text
                    OR title_fuzzy >= trigram_threshold)::integer
                + (path_exact OR path_full_text
                    OR path_fuzzy >= trigram_threshold)::integer
                + (summary_exact OR summary_full_text
                    OR summary_fuzzy >= trigram_threshold)::integer
                + (section_exact OR section_full_text
                    OR section_fuzzy >= trigram_threshold)::integer
                + (body_exact OR body_full_text
                    OR body_fuzzy >= trigram_threshold)::integer
                + (
                    normalized_exact
                    AND NOT (
                        title_exact OR path_exact OR summary_exact
                        OR section_exact OR body_exact
                        OR title_full_text OR path_full_text OR summary_full_text
                        OR section_full_text OR body_full_text
                        OR title_fuzzy >= trigram_threshold
                        OR path_fuzzy >= trigram_threshold
                        OR summary_fuzzy >= trigram_threshold
                        OR section_fuzzy >= trigram_threshold
                        OR body_fuzzy >= trigram_threshold
                    )
                )::integer
            ) AS signal_count,
            ARRAY_REMOVE(
                ARRAY[
                    CASE
                        WHEN title_exact THEN 'title_exact'
                        WHEN title_full_text THEN 'title_full_text'
                        WHEN title_fuzzy >= trigram_threshold THEN 'title_fuzzy'
                    END,
                    CASE
                        WHEN path_exact THEN 'path_exact'
                        WHEN path_full_text THEN 'path_full_text'
                        WHEN path_fuzzy >= trigram_threshold THEN 'path_fuzzy'
                    END,
                    CASE
                        WHEN summary_exact THEN 'summary_exact'
                        WHEN summary_full_text THEN 'summary_full_text'
                        WHEN summary_fuzzy >= trigram_threshold THEN 'summary_fuzzy'
                    END,
                    CASE
                        WHEN section_exact THEN 'section_exact'
                        WHEN section_full_text THEN 'section_full_text'
                        WHEN section_fuzzy >= trigram_threshold THEN 'section_fuzzy'
                    END,
                    CASE
                        WHEN body_exact THEN 'body_exact'
                        WHEN body_full_text THEN 'body_full_text'
                        WHEN body_fuzzy >= trigram_threshold THEN 'body_fuzzy'
                    END,
                    CASE
                        WHEN normalized_exact
                         AND NOT (
                            title_exact OR path_exact OR summary_exact
                            OR section_exact OR body_exact
                            OR title_full_text OR path_full_text OR summary_full_text
                            OR section_full_text OR body_full_text
                            OR title_fuzzy >= trigram_threshold
                            OR path_fuzzy >= trigram_threshold
                            OR summary_fuzzy >= trigram_threshold
                            OR section_fuzzy >= trigram_threshold
                            OR body_fuzzy >= trigram_threshold
                         )
                        THEN 'normalized_exact'
                    END
                ],
                NULL
            ) AS match_reasons
        FROM signals
    )
    SELECT
        document_id,
        path,
        title,
        summary,
        section,
        section_path,
        section_readable,
        ROUND(
            LEAST(
                1.0,
                GREATEST(
                    exact_score,
                    (0.60 * full_text_rank) + (0.40 * fuzzy_score)
                )
                + LEAST(0.04, GREATEST(0, signal_count - 1) * 0.01)
            )::numeric,
            4
        ) AS relevance,
        match_reasons
    FROM ranked
    WHERE CARDINALITY(match_reasons) > 0
    ORDER BY
        relevance DESC,
        path,
        document_id,
        section_ordinal,
        chunk_index
    LIMIT %s
"""
