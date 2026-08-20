"""Add workspace table relation projections.

Revision ID: 20260817_0036
Revises: 20260813_0035
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260817_0036"
down_revision: str | None = "20260813_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_table_relation_generations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("edge_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        # Every stored edge is either rendered or held back as a dead column,
        # which is the only reason a relation is kept out of the page now that
        # both dimensions can state "measured nothing" in their own vocabulary.
        sa.Column("relation_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("hidden_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_task_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "environment IN ('test','uat')",
            name="ck_workspace_table_relation_generations_env",
        ),
        sa.CheckConstraint(
            "status IN ('building','published','superseded','failed')",
            name="ck_workspace_table_relation_generations_status",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_workspace_table_relation_generations_revision",
        ),
        sa.CheckConstraint(
            "edge_count = relation_count + hidden_count",
            name="ck_workspace_table_relation_generations_counts",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_task_id"], ["mcp_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "environment",
            "revision",
            name="uq_workspace_table_relation_generations_revision",
        ),
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

    op.create_table(
        "workspace_table_relation_tables",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("generation_id", sa.String(length=32), nullable=False),
        sa.Column("database_key", sa.String(length=64), nullable=False),
        sa.Column("schema_name", sa.String(length=255), nullable=False),
        sa.Column("table_name", sa.String(length=255), nullable=False),
        # The list is flat, so one counter is all a table card needs. Splitting
        # it per cardinality only made sense while the panel grouped rows, and
        # a relation now carries two cardinalities that can disagree, which no
        # single set of per-cardinality counters could have represented.
        sa.Column("relation_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        # Dead columns are kept out of the list but stay counted, so a table can
        # offer to reveal them without the client fetching what it just hid.
        sa.Column("hidden_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "database_key ~ '^[a-z][a-z0-9_-]{0,63}$'",
            name="ck_workspace_table_relation_tables_database_key",
        ),
        sa.CheckConstraint(
            "relation_count >= 0 AND hidden_count >= 0",
            name="ck_workspace_table_relation_tables_counts",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["workspace_table_relation_generations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_id",
            "database_key",
            "schema_name",
            "table_name",
            name="uq_workspace_table_relation_tables_identity",
        ),
    )
    op.create_index(
        "ix_workspace_table_relation_tables_owner",
        "workspace_table_relation_tables",
        ["generation_id", "database_key", "relation_count"],
    )

    op.create_table(
        "workspace_table_relation_edges",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("generation_id", sa.String(length=32), nullable=False),
        sa.Column("left_database_key", sa.String(length=64), nullable=False),
        sa.Column("left_schema", sa.String(length=255), nullable=False),
        sa.Column("left_table", sa.String(length=255), nullable=False),
        sa.Column("left_column", sa.String(length=255), nullable=False),
        sa.Column("right_database_key", sa.String(length=64), nullable=False),
        sa.Column("right_schema", sa.String(length=255), nullable=False),
        sa.Column("right_table", sa.String(length=255), nullable=False),
        sa.Column("right_column", sa.String(length=255), nullable=False),
        sa.Column("pair_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("orientation", sa.String(length=16), nullable=False),
        # A relation is adjudicated twice over, and the two verdicts are allowed
        # to disagree: what the code permits and what the rows actually contain
        # are different questions. Each verdict is a cardinality plus the kind of
        # evidence it rests on, kept apart so the two cardinalities can sit side
        # by side on a row and be compared without decoding anything.
        sa.Column("code_cardinality", sa.String(length=16), nullable=False),
        sa.Column("code_evidence", sa.String(length=24), nullable=False),
        sa.Column("db_cardinality", sa.String(length=16), nullable=False),
        sa.Column("db_evidence", sa.String(length=24), nullable=False),
        # One timestamp per dimension: they are refreshed on their own schedules,
        # so a shared one could not tell a real disagreement from a stale side.
        sa.Column("code_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("db_measured_at", sa.DateTime(timezone=True), nullable=True),
        # Whether a key is a number or a string, which is the one thing about the
        # endpoints that cannot be read off their names. It decides how an unset
        # value is spelled -- ``0`` for a number, ``''`` for a string -- so the
        # probe a detail view prints can reproduce the counts below rather than
        # merely resemble them. A mismatch between the two ends is also a finding
        # of its own: a numeric key pointing at a string one never joins.
        sa.Column("child_key_kind", sa.String(length=8), nullable=False),
        sa.Column("parent_key_kind", sa.String(length=8), nullable=False),
        # The counts the data verdict was read off. Stored beside the verdict, not
        # because the page needs them to render a row, but because a verdict whose
        # numbers are absent cannot be argued with: with these here the check
        # constraints below can insist the verdict and its evidence agree, and a
        # reader can re-run the probe and land on the same place.
        sa.Column("child_table_rows", sa.Integer(), nullable=False),
        sa.Column("child_rows_with_value", sa.Integer(), nullable=False),
        sa.Column("child_distinct_keys", sa.Integer(), nullable=False),
        # The parent side establishes the precondition the child measurement rests
        # on: N children per key only means N : 1 if the key is unique up there.
        sa.Column("parent_rows_with_value", sa.Integer(), nullable=False),
        sa.Column("parent_distinct_keys", sa.Integer(), nullable=False),
        # Child keys with no surviving parent row. Neither dimension reports this:
        # the code cannot see it and the cardinality probe counts keys without
        # asking whether they resolve.
        sa.Column("orphan_keys", sa.Integer(), nullable=False),
        sa.Column("cross_database", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "orientation IN ('left_to_right','right_to_left','undirected')",
            name="ck_workspace_table_relation_edges_orientation",
        ),
        # Both cardinalities are stored parent-to-child, and a parent can only
        # ever have one or many children, so ``many_to_one`` is a reading rather
        # than a stored value and the read projection derives it by flipping.
        sa.CheckConstraint(
            "code_cardinality IN ('one_to_one','one_to_many','unknown')",
            name="ck_workspace_table_relation_edges_code_cardinality",
        ),
        sa.CheckConstraint(
            "db_cardinality IN ('one_to_one','one_to_many','unknown')",
            name="ck_workspace_table_relation_edges_db_cardinality",
        ),
        sa.CheckConstraint(
            "code_evidence IN ('enforced','single_write','batch_allowed',"
            "'no_write_path','conflicted')",
            name="ck_workspace_table_relation_edges_code_evidence",
        ),
        sa.CheckConstraint(
            "db_evidence IN ('measured','low_sample','never_written','no_data')",
            name="ck_workspace_table_relation_edges_db_evidence",
        ),
        # The evidence that establishes nothing and the cardinality that states
        # nothing have to travel together, otherwise a row could claim to know
        # the multiplicity while admitting it never found a write path.
        sa.CheckConstraint(
            "(code_evidence IN ('no_write_path','conflicted')) = (code_cardinality = 'unknown')",
            name="ck_workspace_table_relation_edges_code_agrees",
        ),
        sa.CheckConstraint(
            "(db_evidence IN ('never_written','no_data')) = (db_cardinality = 'unknown')",
            name="ck_workspace_table_relation_edges_db_agrees",
        ),
        sa.CheckConstraint(
            "child_key_kind IN ('numeric','text') AND parent_key_kind IN ('numeric','text')",
            name="ck_workspace_table_relation_edges_key_kind",
        ),
        # A key cannot be distinct more often than it is present, present more
        # often than there are rows, or dangle more often than it occurs.
        sa.CheckConstraint(
            "child_distinct_keys >= 0"
            " AND child_distinct_keys <= child_rows_with_value"
            " AND child_rows_with_value <= child_table_rows"
            " AND parent_distinct_keys >= 0"
            " AND parent_distinct_keys <= parent_rows_with_value"
            " AND orphan_keys >= 0"
            " AND orphan_keys <= child_distinct_keys",
            name="ck_workspace_table_relation_edges_counts_ordered",
        ),
        # The data verdict is the counts restated, so the two cannot drift apart:
        # one key per row is one-to-one and a repeated key is one-to-many, and
        # there is nothing else a measurement of these two numbers can mean. How
        # many rows are enough to trust the reading is a tuning question and stays
        # out of here, because a threshold baked into a constraint would invalidate
        # every stored row the day it is retuned.
        sa.CheckConstraint(
            "db_evidence NOT IN ('measured','low_sample')"
            " OR (child_rows_with_value > 0"
            " AND (db_cardinality = 'one_to_one')"
            " = (child_distinct_keys = child_rows_with_value))",
            name="ck_workspace_table_relation_edges_db_measured",
        ),
        # The two ways of measuring nothing are told apart by where the emptiness
        # is: a dead column in a populated table, or a table with nothing in it.
        sa.CheckConstraint(
            "db_evidence <> 'never_written'"
            " OR (child_rows_with_value = 0 AND child_table_rows > 0)",
            name="ck_workspace_table_relation_edges_db_never_written",
        ),
        sa.CheckConstraint(
            "db_evidence <> 'no_data' OR child_table_rows = 0",
            name="ck_workspace_table_relation_edges_db_no_data",
        ),
        sa.CheckConstraint(
            "pair_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_workspace_table_relation_edges_fingerprint",
        ),
        # The stored pair is canonical: the smaller endpoint is always the left
        # side, so one relation can never be persisted twice. The comparison is
        # pinned to the C collation so writers can reproduce it byte for byte
        # instead of depending on the database's default collation.
        sa.CheckConstraint(
            '(left_database_key COLLATE "C", left_schema COLLATE "C",'
            ' left_table COLLATE "C", left_column COLLATE "C")'
            ' < (right_database_key COLLATE "C", right_schema COLLATE "C",'
            ' right_table COLLATE "C", right_column COLLATE "C")',
            name="ck_workspace_table_relation_edges_canonical",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["workspace_table_relation_generations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_id",
            "pair_fingerprint",
            name="uq_workspace_table_relation_edges_fingerprint",
        ),
    )
    op.create_index(
        "ix_workspace_table_relation_edges_left_owner",
        "workspace_table_relation_edges",
        ["generation_id", "left_database_key", "left_schema", "left_table"],
    )
    op.create_index(
        "ix_workspace_table_relation_edges_right_owner",
        "workspace_table_relation_edges",
        ["generation_id", "right_database_key", "right_schema", "right_table"],
    )

    # The places in the source a code verdict was read off. The data verdict can
    # publish the queries behind its numbers, and until this table existed the
    # code verdict could publish nothing at all: it arrived as a bare label with
    # a sentence of prose under it, which is a claim a reader can accept or
    # reject but cannot check.
    #
    # Filling it in immediately paid for itself. Four of the six relations whose
    # two verdicts disagreed turned out to disagree only because the code side
    # was wrong, and wrong the same way each time: a ``batchInsert`` had been
    # read as "many children per parent" when the loop around it was minting a
    # fresh parent key per iteration and attaching exactly one child to each.
    # That is why ``kind`` names the thing that decides the multiplicity rather
    # than the persistence call -- the same call appears on both sides of the
    # distinction, so a vocabulary built from call names cannot express it.
    op.create_table(
        "workspace_table_relation_code_sites",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("edge_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        # Where to look, with no coordinate that can rot unnoticed. There is
        # deliberately no line number: it is the one field that would keep
        # looking precise after an edit moved the code, and a site pointing
        # confidently at the wrong line is worse than one that makes the reader
        # search. The method name survives edits that only shift lines, and the
        # snippet is what turns drift into something detectable -- if it is no
        # longer in the file, the site is stale and can be made to say so.
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("method_name", sa.String(length=255), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('fresh_key_per_row','caller_key_reuse','shared_key_fanout',"
            "'single_write','unique_guard','strict_to_map','lossy_read','grouping_by')",
            name="ck_workspace_table_relation_code_sites_kind",
        ),
        # Paths are relative to the workspace root, because an absolute one would
        # be this machine's answer to a question about the repository.
        sa.CheckConstraint(
            "file_path <> '' AND left(file_path, 1) <> '/' AND method_name <> ''",
            name="ck_workspace_table_relation_code_sites_location",
        ),
        # An excerpt, not a copy: a bound here is what keeps a site from
        # accumulating whole files of somebody else's source.
        sa.CheckConstraint(
            "length(snippet) BETWEEN 1 AND 2000",
            name="ck_workspace_table_relation_code_sites_snippet",
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_workspace_table_relation_code_sites_position",
        ),
        sa.ForeignKeyConstraint(
            ["edge_id"],
            ["workspace_table_relation_edges.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "edge_id",
            "position",
            name="uq_workspace_table_relation_code_sites_order",
        ),
    )
    op.create_index(
        "ix_workspace_table_relation_code_sites_edge",
        "workspace_table_relation_code_sites",
        ["edge_id", "position"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_table_relation_code_sites_edge",
        table_name="workspace_table_relation_code_sites",
    )
    op.drop_table("workspace_table_relation_code_sites")
    op.drop_index(
        "ix_workspace_table_relation_edges_right_owner",
        table_name="workspace_table_relation_edges",
    )
    op.drop_index(
        "ix_workspace_table_relation_edges_left_owner",
        table_name="workspace_table_relation_edges",
    )
    op.drop_table("workspace_table_relation_edges")
    op.drop_index(
        "ix_workspace_table_relation_tables_owner",
        table_name="workspace_table_relation_tables",
    )
    op.drop_table("workspace_table_relation_tables")
    op.drop_index(
        "uq_workspace_table_relation_generations_building",
        table_name="workspace_table_relation_generations",
    )
    op.drop_index(
        "uq_workspace_table_relation_generations_published",
        table_name="workspace_table_relation_generations",
    )
    op.drop_table("workspace_table_relation_generations")
