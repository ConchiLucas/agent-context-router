from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from alembic import command
from context_router.repositories import document_search_repository
from context_router.repositories.document_search_repository import (
    DocumentSearchChunkWrite,
    DocumentSearchRepositoryError,
    InMemoryDocumentSearchRepository,
    PostgresDocumentSearchRepository,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REVISION_0011 = "20260725_0011"
_REVISION_0012 = "20260725_0012"
_PROJECT_ID = "a" * 32
_WORKSPACE_ID = "b" * 32
_VERSION_A = "1" * 64
_VERSION_B = "2" * 64


def test_in_memory_repository_replaces_atomically_and_searches_chunk_hits() -> None:
    repository = InMemoryDocumentSearchRepository()
    state = repository.replace_project_index(
        project_id=_PROJECT_ID,
        index_version=_VERSION_A,
        index_format_version=1,
        chunks=[
            _chunk(
                document_id="database-guide",
                path="docs/DATABASE_INFO.md",
                title="数据库信息",
                summary="PostgreSQL migration 与连接说明。",
                section="Migration",
                section_path=("Migration",),
                section_ordinal=1,
                body_text="Run PostgreSQL migrations through Docker Compose.",
            ),
            _chunk(
                document_id="database-guide",
                path="docs/DATABASE_INFO.md",
                title="数据库信息",
                summary="PostgreSQL migration 与连接说明。",
                section="连接配置",
                section_path=("连接配置",),
                section_ordinal=2,
                body_text="控制面数据库名称为 context_router。",
            ),
            _chunk(
                document_id="startup-guide",
                path="docs/STARTUP_GUIDE.md",
                title="启动规范",
                summary="容器启动和测试命令。",
                section="测试",
                section_path=("测试",),
                section_ordinal=1,
                body_text="Execute pytest inside the backend container.",
            ),
        ],
    )

    assert state.document_count == 2
    assert state.chunk_count == 3
    assert repository.get_index_state(_PROJECT_ID) == state

    hits = repository.search(
        project_id=_PROJECT_ID,
        index_version=_VERSION_A,
        query="  PostgreSQL　migration ",
        limit=10,
    )
    assert [(hit.document_id, hit.section) for hit in hits] == [
        ("database-guide", "Migration"),
        ("database-guide", "连接配置"),
    ]
    assert hits[0].relevance > hits[1].relevance
    assert "summary_exact" in hits[0].match_reasons
    assert "body_exact" in hits[0].match_reasons
    assert not hasattr(hits[0], "body_text")

    before = repository.get_index_state(_PROJECT_ID)
    with pytest.raises(DocumentSearchRepositoryError, match="分块位置不能重复"):
        duplicate = _chunk()
        repository.replace_project_index(
            project_id=_PROJECT_ID,
            index_version=_VERSION_B,
            index_format_version=1,
            chunks=[duplicate, duplicate],
        )
    assert repository.get_index_state(_PROJECT_ID) == before
    assert repository.search(
        project_id=_PROJECT_ID,
        index_version=_VERSION_A,
        query="context_router",
        limit=10,
    )


def test_in_memory_repository_supports_fuzzy_search_and_strict_version_isolation() -> None:
    repository = InMemoryDocumentSearchRepository()
    repository.replace_project_index(
        project_id=_PROJECT_ID,
        index_version=_VERSION_A,
        index_format_version=1,
        chunks=[
            _chunk(
                title="Migration handbook",
                body_text="Apply database migrations safely.",
            )
        ],
    )

    fuzzy_hits = repository.search(
        project_id=_PROJECT_ID,
        index_version=_VERSION_A,
        query="migraiton",
        limit=250,
    )
    assert len(fuzzy_hits) == 1
    assert "title_fuzzy" in fuzzy_hits[0].match_reasons
    assert (
        repository.search(
            project_id=_PROJECT_ID,
            index_version=_VERSION_B,
            query="migration",
            limit=10,
        )
        == []
    )


def test_in_memory_repository_indexes_workspace_documents_independently() -> None:
    repository = InMemoryDocumentSearchRepository()
    state = repository.replace_workspace_index(
        workspace_id=_WORKSPACE_ID,
        index_version=_VERSION_A,
        index_format_version=1,
        chunks=[
            _chunk(
                document_id="workspace-entry",
                path="AGENTS.md",
                title="工作空间索引",
                body_text="workspace-only-index-needle",
            )
        ],
    )

    assert repository.get_workspace_index_state(_WORKSPACE_ID) == state
    assert repository.get_index_state(_WORKSPACE_ID) is None
    hits = repository.search_workspace(
        workspace_id=_WORKSPACE_ID,
        index_version=_VERSION_A,
        query="workspace-only-index-needle",
        limit=10,
    )
    assert [hit.document_id for hit in hits] == ["workspace-entry"]

    repository.delete_workspace_index(_WORKSPACE_ID)
    assert repository.get_workspace_index_state(_WORKSPACE_ID) is None


@pytest.mark.parametrize(
    ("query", "limit", "message"),
    [
        ("   ", 10, "搜索关键词不能为空"),
        ("x" * 201, 10, "搜索关键词长度不能超过 200"),
        ("valid", 0, "搜索候选数量必须在 1 到 250 之间"),
        ("valid", 251, "搜索候选数量必须在 1 到 250 之间"),
    ],
)
def test_repository_rejects_unbounded_search_inputs(
    query: str,
    limit: int,
    message: str,
) -> None:
    repository = InMemoryDocumentSearchRepository()
    repository.replace_project_index(
        project_id=_PROJECT_ID,
        index_version=_VERSION_A,
        index_format_version=1,
        chunks=[_chunk()],
    )

    with pytest.raises(DocumentSearchRepositoryError, match=message):
        repository.search(
            project_id=_PROJECT_ID,
            index_version=_VERSION_A,
            query=query,
            limit=limit,
        )


def test_postgres_repository_requires_database_configuration() -> None:
    repository = PostgresDocumentSearchRepository(None)
    with pytest.raises(DocumentSearchRepositoryError, match="任务数据库尚未配置"):
        repository.get_index_state(_PROJECT_ID)


def test_postgres_search_parameter_order_matches_sql_placeholders() -> None:
    parameters = document_search_repository._search_parameters(
        normalized_query="migration",
        trigram_enabled=True,
        project_id=_PROJECT_ID,
        index_version=_VERSION_A,
        limit=250,
    )

    assert parameters == (
        "migration",
        "migration",
        True,
        0.25,
        _PROJECT_ID,
        _VERSION_A,
        250,
    )
    assert document_search_repository._SEARCH_CHUNKS.count("%s") == len(parameters)


@pytest.fixture
def isolated_document_search_database() -> Iterator[str]:
    configured_url = os.getenv("CONTEXT_ROUTER_DATABASE_URL", "").strip()
    if not configured_url:
        pytest.skip("CONTEXT_ROUTER_DATABASE_URL is not configured")

    try:
        configured = make_url(configured_url)
    except Exception:
        pytest.fail("CONTEXT_ROUTER_DATABASE_URL must be a valid PostgreSQL URL", pytrace=False)
    if not configured.drivername.startswith("postgresql"):
        pytest.skip("CONTEXT_ROUTER_DATABASE_URL does not target PostgreSQL")

    database_name = f"acr_document_search_it_{uuid4().hex}"
    admin_url = configured.set(drivername="postgresql").render_as_string(hide_password=False)
    temporary_url = configured.set(
        drivername="postgresql",
        database=database_name,
    ).render_as_string(hide_password=False)
    created = False

    try:
        try:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
                )
            created = True
        except psycopg.errors.InsufficientPrivilege:
            pytest.skip("PostgreSQL role cannot CREATE DATABASE")
        except psycopg.Error as exc:
            pytest.fail(
                "temporary PostgreSQL database creation failed "
                f"(SQLSTATE {exc.sqlstate or 'unknown'})",
                pytrace=False,
            )

        yield temporary_url
    finally:
        if created:
            _drop_temporary_database(admin_url, database_name)


@pytest.mark.postgresql
def test_migration_and_postgres_repository_support_search_and_atomic_replacement(
    isolated_document_search_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = isolated_document_search_database
    monkeypatch.setenv("CONTEXT_ROUTER_DATABASE_URL", database_url)
    alembic_config = _alembic_config()
    command.upgrade(alembic_config, "head")

    with psycopg.connect(database_url) as connection:
        extension = connection.execute(
            "SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'"
        ).fetchone()
        index_names = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'document_search_chunks'
                """
            ).fetchall()
        }
        workspace_index_names = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'workspace_document_search_chunks'
                """
            ).fetchall()
        }
        connection.execute(
            """
            INSERT INTO workspaces
                (id, name, workspace_type, root_path, enabled)
            VALUES (%s, 'Search Workspace', '公司项目', '/search', true)
            """,
            (_PROJECT_ID,),
        )
        connection.execute(
            """
            INSERT INTO document_projects (
                id, name, project_type, project_kind,
                workspace_id, relative_path, agents_path
            )
            VALUES (
                %s, 'Search Project', '公司项目', 'backend',
                %s, '.', '/search/AGENTS.md'
            )
            """,
            (_PROJECT_ID, _PROJECT_ID),
        )
    assert extension == ("pg_trgm",)
    assert {
        "ix_document_search_chunks_search_vector",
        "ix_document_search_chunks_search_text_trgm",
        "ix_document_search_chunks_project_version_document",
    }.issubset(index_names)
    assert {
        "ix_workspace_document_search_chunks_vector",
        "ix_workspace_document_search_chunks_trgm",
        "ix_workspace_document_search_chunks_scope",
    }.issubset(workspace_index_names)

    repository = PostgresDocumentSearchRepository(database_url)
    workspace_state = repository.replace_workspace_index(
        workspace_id=_PROJECT_ID,
        index_version=_VERSION_A,
        index_format_version=1,
        chunks=[
            _chunk(
                document_id="workspace-entry",
                path="AGENTS.md",
                title="工作空间索引",
                body_text="postgres-workspace-index-needle",
            )
        ],
    )
    assert repository.get_workspace_index_state(_PROJECT_ID) == workspace_state
    assert [
        hit.document_id
        for hit in repository.search_workspace(
            workspace_id=_PROJECT_ID,
            index_version=_VERSION_A,
            query="postgres-workspace-index-needle",
            limit=10,
        )
    ] == ["workspace-entry"]
    repository.delete_workspace_index(_PROJECT_ID)
    assert repository.get_workspace_index_state(_PROJECT_ID) is None
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM workspace_document_search_chunks
            WHERE workspace_id = %s
            """,
            (_PROJECT_ID,),
        ).fetchone() == (0,)

    state = repository.replace_project_index(
        project_id=_PROJECT_ID,
        index_version=_VERSION_A,
        index_format_version=1,
        chunks=[
            _chunk(
                document_id="database-guide",
                path="docs/DATABASE_INFO.md",
                title="数据库连接说明",
                summary="说明 PostgreSQL migration 以及 context_router。",
                section="数据库迁移",
                section_path=("数据库迁移",),
                section_ordinal=1,
                body_text="所有 migration 都通过 Docker Compose 执行。",
            ),
            _chunk(
                document_id="startup-guide",
                path="docs/STARTUP_GUIDE.md",
                title="启动规范",
                summary="启动、构建和测试。",
                section="测试",
                section_path=("测试",),
                section_ordinal=1,
                body_text="运行后端 pytest。Ｆｕｌｌｗｉｄｔｈ",
            ),
        ],
    )
    assert repository.get_index_state(_PROJECT_ID) == state
    assert state.document_count == 2
    assert state.chunk_count == 2

    exact_hits = repository.search(
        project_id=_PROJECT_ID,
        index_version=_VERSION_A,
        query="数据库迁移",
        limit=10,
    )
    assert [(hit.document_id, hit.section) for hit in exact_hits] == [
        ("database-guide", "数据库迁移")
    ]
    assert "section_exact" in exact_hits[0].match_reasons
    normalized_hits = repository.search(
        project_id=_PROJECT_ID,
        index_version=_VERSION_A,
        query="fullwidth",
        limit=10,
    )
    assert [hit.document_id for hit in normalized_hits] == ["startup-guide"]
    assert normalized_hits[0].match_reasons == ("normalized_exact",)

    fuzzy_hits = repository.search(
        project_id=_PROJECT_ID,
        index_version=_VERSION_A,
        query="migraiton",
        limit=250,
    )
    assert [hit.document_id for hit in fuzzy_hits] == ["database-guide"]
    assert any(reason.endswith("_fuzzy") for reason in fuzzy_hits[0].match_reasons)
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT set_config('pg_trgm.word_similarity_threshold', '0.25', true)")
        connection.execute("SET LOCAL enable_seqscan = off")
        plan = "\n".join(
            str(row[0])
            for row in connection.execute(
                """
                EXPLAIN
                SELECT id
                FROM document_search_chunks
                WHERE search_text %%> %s
                """,
                ("migraiton",),
            ).fetchall()
        )
    assert "ix_document_search_chunks_search_text_trgm" in plan
    assert (
        repository.search(
            project_id=_PROJECT_ID,
            index_version=_VERSION_A,
            query="%",
            limit=10,
        )
        == []
    )

    repository.replace_project_index(
        project_id=_PROJECT_ID,
        index_version=_VERSION_B,
        index_format_version=2,
        chunks=[_chunk(document_id="replacement", body_text="replacement-only")],
    )
    assert (
        repository.search(
            project_id=_PROJECT_ID,
            index_version=_VERSION_A,
            query="数据库迁移",
            limit=10,
        )
        == []
    )
    assert repository.get_index_state(_PROJECT_ID).index_version == _VERSION_B  # type: ignore[union-attr]

    with psycopg.connect(database_url) as connection:
        connection.execute("DELETE FROM document_projects WHERE id = %s", (_PROJECT_ID,))
        assert connection.execute(
            "SELECT COUNT(*) FROM document_search_chunks WHERE project_id = %s",
            (_PROJECT_ID,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM document_search_index_states WHERE project_id = %s",
            (_PROJECT_ID,),
        ).fetchone() == (0,)

    command.downgrade(alembic_config, _REVISION_0011)
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            "SELECT to_regclass('public.document_search_chunks')"
        ).fetchone() == (None,)
        assert connection.execute(
            "SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'"
        ).fetchone() == ("pg_trgm",)
    command.upgrade(alembic_config, _REVISION_0012)


def _chunk(
    *,
    document_id: str = "document-1",
    path: str = "docs/guide.md",
    title: str | None = "Guide",
    summary: str | None = "Project guide.",
    section: str | None = "Overview",
    section_path: tuple[str, ...] = ("Overview",),
    section_ordinal: int = 1,
    section_readable: bool = True,
    chunk_index: int = 0,
    body_text: str = "General project documentation.",
    content_hash: str = "f" * 64,
) -> DocumentSearchChunkWrite:
    return DocumentSearchChunkWrite(
        document_id=document_id,
        path=path,
        title=title,
        summary=summary,
        section=section,
        section_path=section_path,
        section_ordinal=section_ordinal,
        section_readable=section_readable,
        chunk_index=chunk_index,
        body_text=body_text,
        content_hash=content_hash,
    )


def _alembic_config() -> Config:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "migrations"))
    return config


def _drop_temporary_database(admin_url: str, database_name: str) -> None:
    try:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )
    except psycopg.Error as exc:
        raise AssertionError(
            f"temporary PostgreSQL database cleanup failed (SQLSTATE {exc.sqlstate or 'unknown'})"
        ) from None
