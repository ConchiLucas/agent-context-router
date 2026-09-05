"""add workspace scripts

Revision ID: 20260905_0009
Revises: 20260719_0008
Create Date: 2026-09-05
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision: str = "20260905_0009"
down_revision: str | None = "20260719_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PANZHIHUA_SLUG = "panzhihua-dev-workforce"
PANZHIHUA_NAME = "攀枝花开发工作空间"
PANZHIHUA_ROOT_PATH = "/Users/conchi/workforce/company_workforce/panzhihua_dev_workforce"


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _has_table("workspace_scripts"):
        op.create_table(
            "workspace_scripts",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("slug", sa.String(length=160), nullable=False),
            sa.Column("name", sa.String(length=240), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("kind", sa.String(length=40), nullable=False),
            sa.Column("relative_path", sa.String(length=1024), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "slug", name="uq_workspace_scripts_project_slug"),
            sa.UniqueConstraint(
                "project_id",
                "relative_path",
                name="uq_workspace_scripts_project_path",
            ),
        )
    if not _has_index("workspace_scripts", op.f("ix_workspace_scripts_project_id")):
        op.create_index(
            op.f("ix_workspace_scripts_project_id"),
            "workspace_scripts",
            ["project_id"],
            unique=False,
        )
    if not _has_index("workspace_scripts", op.f("ix_workspace_scripts_slug")):
        op.create_index(op.f("ix_workspace_scripts_slug"), "workspace_scripts", ["slug"], unique=False)
    if not _has_index("workspace_scripts", op.f("ix_workspace_scripts_kind")):
        op.create_index(op.f("ix_workspace_scripts_kind"), "workspace_scripts", ["kind"], unique=False)

    _ensure_panzhihua_project()


def downgrade() -> None:
    if _has_index("workspace_scripts", op.f("ix_workspace_scripts_kind")):
        op.drop_index(op.f("ix_workspace_scripts_kind"), table_name="workspace_scripts")
    if _has_index("workspace_scripts", op.f("ix_workspace_scripts_slug")):
        op.drop_index(op.f("ix_workspace_scripts_slug"), table_name="workspace_scripts")
    if _has_index("workspace_scripts", op.f("ix_workspace_scripts_project_id")):
        op.drop_index(op.f("ix_workspace_scripts_project_id"), table_name="workspace_scripts")
    if _has_table("workspace_scripts"):
        op.drop_table("workspace_scripts")


def _ensure_panzhihua_project() -> None:
    connection = op.get_bind()
    existing_id = connection.execute(
        sa.text("select id from projects where slug = :slug"),
        {"slug": PANZHIHUA_SLUG},
    ).scalar()
    if existing_id is not None:
        return

    now = datetime.now(UTC)
    connection.execute(
        sa.text(
            """
            insert into projects (
                id, slug, name, root_path, description, last_sync_status,
                last_sync_summary, created_at, updated_at
            )
            values (
                :id, :slug, :name, :root_path, :description, :last_sync_status,
                '{}'::json, :created_at, :updated_at
            )
            """
        ),
        {
            "id": str(uuid4()),
            "slug": PANZHIHUA_SLUG,
            "name": PANZHIHUA_NAME,
            "root_path": PANZHIHUA_ROOT_PATH,
            "description": "公司攀枝花开发工作空间。脚本以数据库为编辑源，界面只读。",
            "last_sync_status": "never",
            "created_at": now,
            "updated_at": now,
        },
    )
