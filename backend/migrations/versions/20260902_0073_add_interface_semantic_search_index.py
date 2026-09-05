# ruff: noqa: E501

"""Add the merged interface semantic search index.

Revision ID: 20260902_0073
Revises: 20260827_0072
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260902_0073"
down_revision: str | None = "20260827_0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE TABLE interface_search_workspaces (
            id varchar(36) PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
            name text NOT NULL,
            source_root text NOT NULL DEFAULT '',
            semantic_profile_version text NOT NULL DEFAULT 'v1',
            metadata jsonb NOT NULL DEFAULT '{}',
            active boolean NOT NULL DEFAULT TRUE,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        INSERT INTO interface_search_workspaces (id, name)
        SELECT id, name FROM workspaces
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE TABLE interface_search_workspace_terms (
            id bigserial PRIMARY KEY,
            workspace_id varchar(36) NOT NULL
                REFERENCES interface_search_workspaces(id) ON DELETE CASCADE,
            dimension text NOT NULL,
            canonical_value text NOT NULL,
            aliases text[] NOT NULL DEFAULT '{}',
            mapped_values jsonb NOT NULL DEFAULT '{}',
            metadata jsonb NOT NULL DEFAULT '{}',
            priority integer NOT NULL DEFAULT 0,
            source text NOT NULL DEFAULT 'workspace_config',
            confidence real NOT NULL DEFAULT 1.0
                CHECK (confidence >= 0 AND confidence <= 1),
            active boolean NOT NULL DEFAULT TRUE,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (workspace_id, dimension, canonical_value)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE interface_semantic_index (
            id varchar(36) PRIMARY KEY
                REFERENCES interface_forwarding_interfaces(id) ON DELETE CASCADE,
            workspace_id varchar(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            project text NOT NULL,
            service text NOT NULL,
            method text NOT NULL
                CHECK (method IN ('GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS')),
            path text NOT NULL,
            operation_id text NOT NULL DEFAULT '',
            title text NOT NULL,
            purpose text NOT NULL,
            audiences text[] NOT NULL DEFAULT '{}',
            domains text[] NOT NULL DEFAULT '{}',
            scenarios text[] NOT NULL DEFAULT '{}',
            actions text[] NOT NULL DEFAULT '{}',
            entities text[] NOT NULL DEFAULT '{}',
            aliases text[] NOT NULL DEFAULT '{}',
            resource text NOT NULL DEFAULT '',
            lookup_keys text[] NOT NULL DEFAULT '{}',
            cardinality text NOT NULL DEFAULT 'unknown'
                CHECK (cardinality IN ('unknown', 'one', 'many')),
            ownership text NOT NULL DEFAULT 'unknown'
                CHECK (ownership IN ('unknown', 'self', 'all', 'by_id')),
            discriminators text[] NOT NULL DEFAULT '{}',
            required_inputs jsonb NOT NULL DEFAULT '[]',
            request_schema_paths jsonb NOT NULL DEFAULT '[]',
            response_schema_paths jsonb NOT NULL DEFAULT '[]',
            business_identifiers jsonb NOT NULL DEFAULT '[]',
            semantic_field_sources jsonb NOT NULL DEFAULT '{}',
            semantic_confidences jsonb NOT NULL DEFAULT '{}',
            search_document_version text NOT NULL DEFAULT 'v3',
            embedding_version text NOT NULL DEFAULT 'local-feature-v1',
            controller_name text NOT NULL DEFAULT '',
            interface_family text NOT NULL DEFAULT '',
            sibling_actions jsonb NOT NULL DEFAULT '{}',
            distinguishing_features jsonb NOT NULL DEFAULT '{}',
            family_size integer NOT NULL DEFAULT 1 CHECK (family_size >= 1),
            tags text[] NOT NULL DEFAULT '{}',
            request_schema jsonb NOT NULL DEFAULT '{}',
            response_schema jsonb NOT NULL DEFAULT '{}',
            source_locations text[] NOT NULL DEFAULT '{}',
            semantic_source text NOT NULL DEFAULT 'bootstrap',
            semantic_model text NOT NULL DEFAULT '',
            semantic_confidence real NOT NULL DEFAULT 0.5
                CHECK (semantic_confidence >= 0 AND semantic_confidence <= 1),
            semantic_evidence text[] NOT NULL DEFAULT '{}',
            search_document text NOT NULL DEFAULT '',
            search_document_zh text NOT NULL DEFAULT '',
            search_tsvector tsvector
                GENERATED ALWAYS AS (to_tsvector('simple', search_document)) STORED,
            search_tsvector_zh tsvector
                GENERATED ALWAYS AS (to_tsvector('simple', search_document_zh)) STORED,
            embedding vector(1024),
            contract_hash text NOT NULL DEFAULT '',
            contract_hash_version text NOT NULL DEFAULT 'v1',
            semantic_stale boolean NOT NULL DEFAULT false,
            active boolean NOT NULL DEFAULT true,
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (workspace_id, project, service, method, path)
        )
        """
    )
    op.execute(
        """
        INSERT INTO interface_semantic_index (
            id, workspace_id, project, service, method, path, operation_id,
            title, purpose, actions, entities, aliases, controller_name,
            request_schema, response_schema, semantic_source, semantic_model,
            semantic_confidence, semantic_evidence, search_document,
            search_document_zh, contract_hash
        )
        SELECT
            interface.id,
            interface.workspace_id,
            workspace.name,
            service.name,
            upper(interface.method),
            interface.path,
            interface.operation_id,
            interface.name,
            COALESCE(NULLIF(profile.business_scenario, ''),
                     NULLIF(interface.description, ''), interface.name),
            CASE
                WHEN NULLIF(profile.business_action, '') IS NULL THEN ARRAY[]::text[]
                ELSE ARRAY[profile.business_action]
            END,
            CASE
                WHEN NULLIF(profile.business_entity, '') IS NULL THEN ARRAY[]::text[]
                ELSE ARRAY[profile.business_entity]
            END,
            COALESCE(
                ARRAY(SELECT jsonb_array_elements_text(COALESCE(profile.aliases, '[]'::jsonb))),
                ARRAY[]::text[]
            ),
            interface.controller_name,
            interface.request_schema,
            interface.response_schema,
            'legacy_import',
            'agent-context-router-legacy',
            COALESCE(profile.confidence::real / 100.0, 0.35),
            ARRAY['migrated_from_interface_forwarding'],
            concat_ws(E'\n',
                '用途: ' || COALESCE(NULLIF(profile.business_scenario, ''),
                                    NULLIF(interface.description, ''), interface.name),
                '实体: ' || COALESCE(profile.business_entity, ''),
                '动作: ' || COALESCE(profile.business_action, ''),
                '别名: ' || COALESCE(profile.aliases::text, ''),
                '路径: ' || interface.path,
                '操作标识: ' || interface.operation_id,
                '项目服务: ' || workspace.name || ' ' || service.name || ' ' || upper(interface.method)
            ),
            concat_ws(' ', interface.name, interface.description, interface.path,
                      interface.operation_id, interface.controller_name),
            md5(concat_ws('|', upper(interface.method), interface.path,
                          interface.request_schema::text, interface.response_schema::text))
        FROM interface_forwarding_interfaces AS interface
        JOIN interface_forwarding_services AS service ON service.id = interface.service_id
        JOIN workspaces AS workspace ON workspace.id = interface.workspace_id
        LEFT JOIN interface_forwarding_intent_profiles AS profile
          ON profile.interface_id = interface.id
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        "CREATE INDEX ix_interface_semantic_workspace_active "
        "ON interface_semantic_index(workspace_id, active, project, service, method)"
    )
    op.execute(
        "CREATE INDEX ix_interface_semantic_search_tsvector "
        "ON interface_semantic_index USING gin(search_tsvector)"
    )
    op.execute(
        "CREATE INDEX ix_interface_semantic_search_tsvector_zh "
        "ON interface_semantic_index USING gin(search_tsvector_zh)"
    )
    op.execute(
        "CREATE INDEX ix_interface_semantic_search_trgm "
        "ON interface_semantic_index USING gin(search_document gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_interface_semantic_embedding_hnsw "
        "ON interface_semantic_index USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_interface_semantic_lookup_keys "
        "ON interface_semantic_index USING gin(lookup_keys)"
    )
    op.execute(
        "CREATE INDEX ix_interface_semantic_business_identifiers "
        "ON interface_semantic_index USING gin(business_identifiers jsonb_path_ops)"
    )
    op.execute(
        "CREATE INDEX ix_interface_search_workspace_terms_lookup "
        "ON interface_search_workspace_terms(workspace_id, dimension) WHERE active"
    )
    op.execute(
        """
        CREATE TABLE interface_search_feedback (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            search_id uuid NOT NULL,
            query text NOT NULL,
            selected_interface_id varchar(36)
                REFERENCES interface_forwarding_interfaces(id) ON DELETE SET NULL,
            expected_interface_id varchar(36)
                REFERENCES interface_forwarding_interfaces(id) ON DELETE SET NULL,
            relevant boolean,
            result_ranking jsonb NOT NULL DEFAULT '[]',
            note text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE interface_search_sessions (
            search_id uuid PRIMARY KEY,
            query text NOT NULL,
            filters jsonb NOT NULL DEFAULT '{}',
            response jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_interface_search_sessions_expires_at "
        "ON interface_search_sessions(expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS interface_search_sessions")
    op.execute("DROP TABLE IF EXISTS interface_search_feedback")
    op.execute("DROP TABLE IF EXISTS interface_semantic_index")
    op.execute("DROP TABLE IF EXISTS interface_search_workspace_terms")
    op.execute("DROP TABLE IF EXISTS interface_search_workspaces")
