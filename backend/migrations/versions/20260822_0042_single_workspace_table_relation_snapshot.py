"""Use one published table-relation snapshot per workspace.

Revision ID: 20260822_0042
Revises: 20260821_0041
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0042"
down_revision: str | None = "20260821_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY workspace_id
                           ORDER BY published_at DESC NULLS LAST, created_at DESC, id DESC
                       ) AS position
                FROM workspace_table_relation_generations
                WHERE status = 'published'
            )
            UPDATE workspace_table_relation_generations AS generation
            SET status = 'superseded', updated_at = CURRENT_TIMESTAMP
            FROM ranked
            WHERE generation.id = ranked.id AND ranked.position > 1
            """
        )
    )
    connection.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY workspace_id
                           ORDER BY started_at DESC, created_at DESC, id DESC
                       ) AS position
                FROM workspace_table_relation_generations
                WHERE status = 'building'
            )
            UPDATE workspace_table_relation_generations AS generation
            SET status = 'failed',
                failed_at = CURRENT_TIMESTAMP,
                error_code = 'superseded_by_single_snapshot_migration',
                error_message = '工作空间只保留一个构建中的表关联版本',
                updated_at = CURRENT_TIMESTAMP
            FROM ranked
            WHERE generation.id = ranked.id AND ranked.position > 1
            """
        )
    )

    op.drop_index(
        "uq_workspace_table_relation_generations_published",
        table_name="workspace_table_relation_generations",
    )
    op.drop_index(
        "uq_workspace_table_relation_generations_building",
        table_name="workspace_table_relation_generations",
    )
    op.create_index(
        "uq_workspace_table_relation_generations_published",
        "workspace_table_relation_generations",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_index(
        "uq_workspace_table_relation_generations_building",
        "workspace_table_relation_generations",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("status = 'building'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_workspace_table_relation_generations_building",
        table_name="workspace_table_relation_generations",
    )
    op.drop_index(
        "uq_workspace_table_relation_generations_published",
        table_name="workspace_table_relation_generations",
    )
    op.create_index(
        "uq_workspace_table_relation_generations_published",
        "workspace_table_relation_generations",
        ["workspace_id", "environment"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_index(
        "uq_workspace_table_relation_generations_building",
        "workspace_table_relation_generations",
        ["workspace_id", "environment"],
        unique=True,
        postgresql_where=sa.text("status = 'building'"),
    )
