"""Add database MCP aliases and call history.

Revision ID: 20260722_0008
Revises: 20260722_0007
Create Date: 2026-07-22
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0008"
down_revision: str | None = "20260722_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INVALID_ALIAS_CHARACTERS = re.compile(r"[^a-z0-9]+")


def _stable_link_token(link_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", link_id.lower())
    if len(normalized) >= 8:
        return normalized
    return hashlib.sha256(link_id.encode()).hexdigest()


def _alias_candidate(*values: object, link_id: str) -> str:
    for value in values:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
        slug = _INVALID_ALIAS_CHARACTERS.sub("_", ascii_value).strip("_")
        if not slug:
            continue
        if not slug[0].isalpha():
            slug = f"db_{slug}"
        return slug[:64].rstrip("_")
    return f"db_{_stable_link_token(link_id)[:8]}"


def _unique_alias(base: str, *, link_id: str, used: set[str]) -> str:
    if base.casefold() not in used:
        return base
    token = _stable_link_token(link_id)
    suffix_candidates = [token[:length] for length in range(8, len(token) + 1, 4)]
    digest = hashlib.sha256(link_id.encode()).hexdigest()
    suffix_candidates.extend(digest[:length] for length in range(8, len(digest) + 1, 4))
    for suffix in suffix_candidates:
        candidate = f"{base[: 63 - len(suffix)].rstrip('_')}_{suffix}"
        if candidate.casefold() not in used:
            return candidate
    raise RuntimeError("Unable to generate a unique MCP database alias")


def _backfill_mcp_aliases() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT
                link.id,
                link.project_id,
                link.alias,
                database.display_name,
                database.remote_name
            FROM project_databases AS link
            JOIN data_source_databases AS database ON database.id = link.database_id
            ORDER BY link.project_id, link.created_at, link.id
            """
        )
    ).fetchall()
    aliases_by_project: dict[str, set[str]] = {}
    for row in rows:
        link_id = str(row[0])
        project_id = str(row[1])
        used = aliases_by_project.setdefault(project_id, set())
        base = _alias_candidate(row[2], row[3], row[4], link_id=link_id)
        mcp_alias = _unique_alias(base, link_id=link_id, used=used)
        connection.execute(
            sa.text("UPDATE project_databases SET mcp_alias = :mcp_alias WHERE id = :link_id"),
            {"mcp_alias": mcp_alias, "link_id": link_id},
        )
        used.add(mcp_alias.casefold())


def upgrade() -> None:
    op.add_column(
        "project_databases",
        sa.Column("mcp_alias", sa.String(length=64), nullable=True),
    )
    _backfill_mcp_aliases()
    op.create_check_constraint(
        "ck_project_databases_mcp_alias",
        "project_databases",
        "mcp_alias IS NULL OR mcp_alias ~ '^[a-z][a-z0-9_-]{0,63}$'",
    )
    op.create_index(
        "uq_project_databases_project_mcp_alias",
        "project_databases",
        ["project_id", sa.text("lower(mcp_alias)")],
        unique=True,
        postgresql_where=sa.text("mcp_alias IS NOT NULL"),
    )

    op.create_table(
        "mcp_database_calls",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("database_alias", sa.String(length=64), nullable=False),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=True),
        sa.Column("statement_type", sa.String(length=32), nullable=True),
        sa.Column("sql_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("returned_count", sa.Integer(), nullable=True),
        sa.Column("result_bytes", sa.Integer(), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "operation IN ('search_objects','execute_query')",
            name="ck_mcp_database_calls_operation",
        ),
        sa.CheckConstraint("status IN ('ok','error')", name="ck_mcp_database_calls_status"),
        sa.CheckConstraint(
            "sql_sha256 IS NULL OR sql_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_mcp_database_calls_sql_sha256",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_mcp_database_calls_duration_ms",
        ),
        sa.CheckConstraint(
            "returned_count IS NULL OR returned_count >= 0",
            name="ck_mcp_database_calls_returned_count",
        ),
        sa.CheckConstraint(
            "result_bytes IS NULL OR result_bytes >= 0",
            name="ck_mcp_database_calls_result_bytes",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["mcp_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mcp_database_calls_task_id_id",
        "mcp_database_calls",
        ["task_id", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_database_calls_task_id_id", table_name="mcp_database_calls")
    op.drop_table("mcp_database_calls")
    op.drop_index(
        "uq_project_databases_project_mcp_alias",
        table_name="project_databases",
    )
    op.drop_constraint(
        "ck_project_databases_mcp_alias",
        "project_databases",
        type_="check",
    )
    op.drop_column("project_databases", "mcp_alias")
