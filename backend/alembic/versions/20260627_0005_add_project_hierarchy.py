"""add project hierarchy

Revision ID: 20260627_0005
Revises: 20260627_0004
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260627_0005"
down_revision: str | None = "20260627_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKFORCE_ROOT_SLUG = "rob-english-word-workforce"
WORKFORCE_CHILD_SLUGS = (
    "rob-english-word-back",
    "rob-english-word-cloze-web",
    "rob-english-word-front",
    "word-agent",
    "word-select-dashboard",
    "word-select-dashboard-server",
    "word-select-dashboard-web-react",
)


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _has_foreign_key(table_name: str, foreign_key_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        foreign_key["name"] == foreign_key_name
        for foreign_key in inspector.get_foreign_keys(table_name)
    )


def upgrade() -> None:
    if not _has_column("projects", "parent_project_id"):
        op.add_column(
            "projects",
            sa.Column("parent_project_id", sa.String(length=36), nullable=True),
        )
    if not _has_index("projects", op.f("ix_projects_parent_project_id")):
        op.create_index(
            op.f("ix_projects_parent_project_id"),
            "projects",
            ["parent_project_id"],
            unique=False,
        )

    if not _has_foreign_key("projects", "fk_projects_parent_project_id_projects"):
        op.create_foreign_key(
            "fk_projects_parent_project_id_projects",
            "projects",
            "projects",
            ["parent_project_id"],
            ["id"],
            ondelete="SET NULL",
        )

    _attach_workforce_child_projects()


def downgrade() -> None:
    if _has_foreign_key("projects", "fk_projects_parent_project_id_projects"):
        op.drop_constraint(
            "fk_projects_parent_project_id_projects",
            "projects",
            type_="foreignkey",
        )
    if _has_index("projects", op.f("ix_projects_parent_project_id")):
        op.drop_index(op.f("ix_projects_parent_project_id"), table_name="projects")
    if _has_column("projects", "parent_project_id"):
        op.drop_column("projects", "parent_project_id")


def _attach_workforce_child_projects() -> None:
    connection = op.get_bind()
    root_id = connection.execute(
        sa.text("select id from projects where slug = :slug"),
        {"slug": WORKFORCE_ROOT_SLUG},
    ).scalar()
    if root_id is None:
        return

    statement = sa.text(
        """
        update projects
        set parent_project_id = :root_id
        where slug in :child_slugs
        """
    ).bindparams(sa.bindparam("child_slugs", expanding=True))
    connection.execute(
        statement,
        {"root_id": root_id, "child_slugs": list(WORKFORCE_CHILD_SLUGS)},
    )
