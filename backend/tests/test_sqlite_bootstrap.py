from sqlalchemy import create_engine, inspect

from context_router.db.session import ensure_sqlite_schema


def test_ensure_sqlite_schema_creates_tables_for_local_first_database(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'context_router.db'}")

    ensure_sqlite_schema(engine)

    table_names = set(inspect(engine).get_table_names())
    assert {"projects", "documents", "traces", "trace_events", "retrieval_hits"}.issubset(
        table_names
    )
    project_columns = {column["name"] for column in inspect(engine).get_columns("projects")}
    document_columns = {column["name"] for column in inspect(engine).get_columns("documents")}
    assert {
        "docs_path",
        "last_synced_at",
        "last_sync_status",
        "last_sync_summary",
    }.issubset(project_columns)
    assert {"is_reachable", "graph_depth"}.issubset(document_columns)
