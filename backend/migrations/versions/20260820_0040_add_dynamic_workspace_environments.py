"""Replace fixed TEST/UAT selectors with dynamic Workspace environments.

Revision ID: 20260820_0040
Revises: 20260820_0039
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260820_0040"
down_revision: str | None = "20260820_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_environments",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("environment_key", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "environment_key ~ '^[a-z][a-z0-9_-]{0,31}$'",
            name="ck_workspace_environments_key",
        ),
        sa.CheckConstraint(
            "btrim(display_name) <> ''",
            name="ck_workspace_environments_display_name",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "environment_key"),
    )
    op.create_index(
        "uq_workspace_environments_default",
        "workspace_environments",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    # Local exists for every Workspace. Other keys are recovered only from
    # actual saved configuration; they are not globally manufactured.
    op.execute(
        """
        INSERT INTO workspace_environments (
            workspace_id, environment_key, display_name, sort_order, is_default
        )
        SELECT id, 'local', 'LOCAL', 0, true
        FROM workspaces
        """
    )

    op.drop_constraint(
        "ck_workspace_database_environment_configs_active",
        "workspace_database_environment_configs",
        type_="check",
    )
    op.drop_constraint(
        "ck_project_database_environment_targets_environment",
        "project_database_environment_targets",
        type_="check",
    )
    op.drop_constraint(
        "ck_workspace_environment_payloads_environment",
        "workspace_environment_payloads",
        type_="check",
    )
    op.drop_constraint(
        "ck_workspace_nacos_profiles_key",
        "workspace_nacos_profiles",
        type_="check",
    )
    op.alter_column(
        "workspace_nacos_profiles",
        "profile_key",
        type_=sa.String(length=32),
        existing_type=sa.String(length=8),
    )
    for table_name, column_name in (
        ("workspace_database_environment_configs", "active_environment"),
        ("project_database_environment_targets", "environment"),
        ("workspace_environment_payloads", "environment"),
        ("mcp_tasks", "database_environment"),
        ("workspace_table_relation_generations", "environment"),
    ):
        op.alter_column(
            table_name,
            column_name,
            type_=sa.String(length=32),
            existing_type=sa.String(length=16),
        )
    op.execute(
        "UPDATE workspace_nacos_profiles SET profile_key = 'local' WHERE profile_key = 'default'"
    )

    op.drop_constraint("ck_mcp_tasks_database_environment", "mcp_tasks", type_="check")
    op.create_check_constraint(
        "ck_mcp_tasks_database_environment",
        "mcp_tasks",
        """
        (
            database_environment IS NULL
            AND database_environment_revision IS NULL
            AND database_environment_selection IS NULL
        )
        OR (
            database_environment IS NOT NULL
            AND database_environment ~ '^[a-z][a-z0-9_-]{0,31}$'
            AND database_environment_revision IS NOT NULL
            AND database_environment_revision > 0
            AND database_environment_selection IS NOT NULL
            AND database_environment_selection IN (
                'workspace_default', 'task_explicit'
            )
        )
        """,
    )

    op.drop_constraint(
        "ck_workspace_table_relation_generations_env",
        "workspace_table_relation_generations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workspace_table_relation_generations_env",
        "workspace_table_relation_generations",
        "environment ~ '^[a-z][a-z0-9_-]{0,31}$'",
    )

    # Existing mappings become explicitly available in local as well. Prefer
    # the already-authorized link carrying the same MCP alias; otherwise retain
    # the old TEST target as the compatibility target. This does not give the
    # database an environment identity—the target row is the association.
    op.execute(
        """
        INSERT INTO project_database_environment_targets (
            mapping_id, environment, project_database_id
        )
        SELECT
            mapping.id,
            'local',
            COALESCE(alias_link.id, test_target.project_database_id, uat_target.project_database_id)
        FROM project_database_environment_mappings AS mapping
        LEFT JOIN project_databases AS alias_link
          ON alias_link.project_id = mapping.project_id
         AND lower(alias_link.mcp_alias) = lower(mapping.mcp_alias)
        LEFT JOIN project_database_environment_targets AS test_target
          ON test_target.mapping_id = mapping.id AND test_target.environment = 'test'
        LEFT JOIN project_database_environment_targets AS uat_target
          ON uat_target.mapping_id = mapping.id AND uat_target.environment = 'uat'
        WHERE COALESCE(
            alias_link.id,
            test_target.project_database_id,
            uat_target.project_database_id
        )
              IS NOT NULL
        ON CONFLICT (mapping_id, environment) DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO workspace_environments (
            workspace_id, environment_key, display_name, sort_order, is_default
        )
        SELECT DISTINCT found.workspace_id,
               found.environment_key,
               upper(found.environment_key),
               CASE found.environment_key WHEN 'test' THEN 10 WHEN 'uat' THEN 20 ELSE 100 END,
               false
        FROM (
            SELECT mapping.workspace_id, target.environment AS environment_key
            FROM project_database_environment_targets AS target
            JOIN project_database_environment_mappings AS mapping ON mapping.id = target.mapping_id
            UNION
            SELECT workspace_id, environment FROM workspace_environment_payloads
            UNION
            SELECT workspace_id, profile_key FROM workspace_nacos_profiles
            UNION
            SELECT workspace_id, environment FROM workspace_table_relation_generations
            UNION
            SELECT workspace_id, database_environment
            FROM mcp_tasks
            WHERE workspace_id IS NOT NULL AND database_environment IS NOT NULL
        ) AS found
        WHERE found.environment_key <> 'local'
          AND found.environment_key ~ '^[a-z][a-z0-9_-]{0,31}$'
        ON CONFLICT (workspace_id, environment_key) DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO workspace_database_environment_configs (
            workspace_id, active_environment, revision
        )
        SELECT id, 'local', 1 FROM workspaces
        ON CONFLICT (workspace_id) DO UPDATE SET
            active_environment = 'local',
            revision = workspace_database_environment_configs.revision + 1,
            updated_at = CURRENT_TIMESTAMP
        """
    )

    op.create_foreign_key(
        "fk_workspace_environment_configs_active",
        "workspace_database_environment_configs",
        "workspace_environments",
        ["workspace_id", "active_environment"],
        ["workspace_id", "environment_key"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_workspace_environment_payloads_environment",
        "workspace_environment_payloads",
        "workspace_environments",
        ["workspace_id", "environment"],
        ["workspace_id", "environment_key"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_workspace_nacos_profiles_environment",
        "workspace_nacos_profiles",
        "workspace_environments",
        ["workspace_id", "profile_key"],
        ["workspace_id", "environment_key"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_workspace_table_relation_generations_environment",
        "workspace_table_relation_generations",
        "workspace_environments",
        ["workspace_id", "environment"],
        ["workspace_id", "environment_key"],
        ondelete="CASCADE",
    )

    # The per-tool table represented the superseded model. Environment-aware
    # tools now share the task/Workspace environment and local is the default.
    op.execute(
        """
        UPDATE mcp_tasks
        SET database_environment_selection = 'workspace_default'
        WHERE database_environment_selection = 'tool_default'
        """
    )
    op.drop_table("workspace_mcp_environment_defaults")


def downgrade() -> None:
    op.create_table(
        "workspace_mcp_environment_defaults",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("default_environment", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "tool_name"),
    )
    op.drop_constraint(
        "fk_workspace_table_relation_generations_environment",
        "workspace_table_relation_generations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_workspace_nacos_profiles_environment", "workspace_nacos_profiles", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_workspace_environment_payloads_environment",
        "workspace_environment_payloads",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_workspace_environment_configs_active",
        "workspace_database_environment_configs",
        type_="foreignkey",
    )
    op.execute(
        "DELETE FROM workspace_table_relation_generations WHERE environment NOT IN ('test','uat')"
    )
    op.execute("DELETE FROM workspace_environment_payloads WHERE environment NOT IN ('test','uat')")
    op.execute(
        "DELETE FROM project_database_environment_targets WHERE environment NOT IN ('test','uat')"
    )
    op.execute(
        "DELETE FROM workspace_nacos_profiles WHERE profile_key NOT IN ('local','test','uat')"
    )
    op.execute(
        "UPDATE workspace_nacos_profiles SET profile_key = 'default' WHERE profile_key = 'local'"
    )
    op.execute("UPDATE workspace_database_environment_configs SET active_environment = 'uat'")
    op.execute(
        """
        UPDATE mcp_tasks SET database_environment = NULL,
            database_environment_revision = NULL,
            database_environment_selection = NULL
        WHERE database_environment NOT IN ('test','uat')
        """
    )
    op.alter_column(
        "workspace_nacos_profiles",
        "profile_key",
        type_=sa.String(length=8),
        existing_type=sa.String(length=32),
    )
    for table_name, column_name in (
        ("workspace_database_environment_configs", "active_environment"),
        ("project_database_environment_targets", "environment"),
        ("workspace_environment_payloads", "environment"),
        ("mcp_tasks", "database_environment"),
        ("workspace_table_relation_generations", "environment"),
    ):
        op.alter_column(
            table_name,
            column_name,
            type_=sa.String(length=16),
            existing_type=sa.String(length=32),
        )
    op.create_check_constraint(
        "ck_workspace_nacos_profiles_key",
        "workspace_nacos_profiles",
        "profile_key IN ('default','test','uat')",
    )
    op.create_check_constraint(
        "ck_workspace_environment_payloads_environment",
        "workspace_environment_payloads",
        "environment IN ('test','uat')",
    )
    op.create_check_constraint(
        "ck_project_database_environment_targets_environment",
        "project_database_environment_targets",
        "environment IN ('test','uat')",
    )
    op.create_check_constraint(
        "ck_workspace_database_environment_configs_active",
        "workspace_database_environment_configs",
        "active_environment IN ('test','uat')",
    )
    op.drop_constraint("ck_mcp_tasks_database_environment", "mcp_tasks", type_="check")
    op.create_check_constraint(
        "ck_mcp_tasks_database_environment",
        "mcp_tasks",
        """(database_environment IS NULL AND database_environment_revision IS NULL
        AND database_environment_selection IS NULL) OR
        (database_environment IN ('test','uat') AND database_environment_revision > 0
        AND database_environment_selection IN (
            'workspace_default','task_explicit','tool_default'
        ))""",
    )
    op.drop_constraint(
        "ck_workspace_table_relation_generations_env",
        "workspace_table_relation_generations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workspace_table_relation_generations_env",
        "workspace_table_relation_generations",
        "environment IN ('test','uat')",
    )
    op.drop_index("uq_workspace_environments_default", table_name="workspace_environments")
    op.drop_table("workspace_environments")
