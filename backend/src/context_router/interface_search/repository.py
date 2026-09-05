# ruff: noqa: E501

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from context_router.interface_search.domain import EndpointRecord, SearchFilters, SearchResponse
from context_router.interface_search.embedding import cosine_similarity, tokenize
from context_router.interface_search.families import sibling_action_keys
from context_router.interface_search.workspaces import WorkspaceProfile, WorkspaceTerm

SemanticQueueMode = Literal["all", "unscanned", "stale", "low-confidence"]


@dataclass
class Candidate:
    endpoint: EndpointRecord
    lexical_score: float
    vector_score: float
    exact_score: float
    schema_recall_score: float = 0
    structured_recall_score: float = 0
    family_recall_score: float = 0
    identifier_recall_score: float = 0
    service_recall_score: float = 0
    field_recall_score: float = 0


class EndpointRepository(Protocol):
    def count(self) -> int: ...

    def add_many(self, endpoints: Iterable[EndpointRecord]) -> list[EndpointRecord]: ...

    def get(self, endpoint_id: str) -> EndpointRecord | None: ...

    def list_interfaces(
        self,
        *,
        workspace_id: str = "",
        query: str,
        service: str | None,
        method: str | None,
        semantic_status: str,
        offset: int,
        limit: int,
    ) -> tuple[int, list[EndpointRecord]]: ...

    def candidates(
        self,
        *,
        workspace_id: str = "",
        query: str,
        query_embedding: list[float],
        exact_identifiers: list[str],
        filters: SearchFilters,
        limit: int,
        soft_audiences: list[str] | None = None,
        soft_domains: list[str] | None = None,
        soft_actions: list[str] | None = None,
        soft_services: list[str] | None = None,
        soft_resource: str = "",
        soft_lookup_keys: list[str] | None = None,
        soft_identifier_types: list[str] | None = None,
        soft_cardinality: str = "unknown",
        soft_field_identifiers: list[str] | None = None,
        schema_direction: str = "unknown",
    ) -> list[Candidate]: ...

    def record_feedback(self, payload: dict) -> None: ...

    def feedback_count(self) -> int: ...

    def semantic_queue(
        self,
        *,
        project: str | None,
        max_confidence: float,
        limit: int,
        services: list[str] | None = None,
        mode: SemanticQueueMode = "all",
    ) -> tuple[int, list[EndpointRecord]]: ...

    def save_search_session(
        self, response: SearchResponse, filters: SearchFilters, *, ttl_days: int
    ) -> None: ...

    def get_search_session(self, search_id: str) -> SearchResponse | None: ...

    def delete_expired_search_sessions(self) -> int: ...

    def mark_unseen_inactive(
        self, project: str, seen_ids: list[str], *, workspace_id: str = ""
    ) -> int: ...

    def rebuild_interface_families(self) -> int: ...

    def list_workspaces(self) -> list[WorkspaceProfile]: ...

    def get_workspace_profile(self, workspace_id: str) -> WorkspaceProfile | None: ...

    def save_workspace_profile(self, profile: WorkspaceProfile) -> None: ...


class InMemoryEndpointRepository:
    def __init__(self) -> None:
        self._items: dict[str, EndpointRecord] = {}
        self._feedback: list[dict] = []
        self._search_sessions: dict[str, SearchResponse] = {}
        self._workspace_profiles: dict[str, WorkspaceProfile] = {}

    def count(self) -> int:
        return sum(item.active for item in self._items.values())

    def add_many(self, endpoints: Iterable[EndpointRecord]) -> list[EndpointRecord]:
        saved = []
        for endpoint in endpoints:
            existing = next(
                (
                    item
                    for item in self._items.values()
                    if (
                        item.workspace_id,
                        item.project,
                        item.service,
                        item.method,
                        item.path,
                    )
                    == (
                        endpoint.workspace_id,
                        endpoint.project,
                        endpoint.service,
                        endpoint.method,
                        endpoint.path,
                    )
                ),
                None,
            )
            persisted = _merge_endpoint(existing, endpoint) if existing else endpoint
            self._items[persisted.id] = persisted
            saved.append(persisted)
        return saved

    def list_workspaces(self) -> list[WorkspaceProfile]:
        return sorted(self._workspace_profiles.values(), key=lambda item: item.workspace_id)

    def get_workspace_profile(self, workspace_id: str) -> WorkspaceProfile | None:
        return self._workspace_profiles.get(workspace_id)

    def save_workspace_profile(self, profile: WorkspaceProfile) -> None:
        self._workspace_profiles[profile.workspace_id] = profile

    def get(self, endpoint_id: str) -> EndpointRecord | None:
        return self._items.get(endpoint_id)

    def list_interfaces(
        self,
        *,
        workspace_id: str = "",
        query: str,
        service: str | None,
        method: str | None,
        semantic_status: str,
        offset: int,
        limit: int,
    ) -> tuple[int, list[EndpointRecord]]:
        normalized_query = query.strip().lower()
        normalized_service = service.strip().lower() if service else ""
        items = []
        for endpoint in self._items.values():
            if not endpoint.active:
                continue
            if workspace_id and endpoint.workspace_id != workspace_id:
                continue
            searchable = " ".join(
                [
                    endpoint.search_document,
                    endpoint.path,
                    endpoint.operation_id,
                    endpoint.title,
                    endpoint.purpose,
                ]
            ).lower()
            if normalized_query and normalized_query not in searchable:
                continue
            if normalized_service and normalized_service not in endpoint.service.lower():
                continue
            if method and endpoint.method != method:
                continue
            is_llm = endpoint.semantic_source == "llm_source_analysis"
            if semantic_status == "llm" and not is_llm:
                continue
            if semantic_status == "bootstrap" and is_llm:
                continue
            items.append(endpoint)
        items.sort(
            key=lambda endpoint: (
                endpoint.semantic_source != "llm_source_analysis",
                -endpoint.updated_at.timestamp(),
                endpoint.path,
                endpoint.id,
            )
        )
        return len(items), items[offset : offset + limit]

    def record_feedback(self, payload: dict) -> None:
        self._feedback.append(payload)

    def feedback_count(self) -> int:
        return len(self._feedback)

    def semantic_queue(
        self,
        *,
        project: str | None,
        max_confidence: float,
        limit: int,
        services: list[str] | None = None,
        mode: SemanticQueueMode = "all",
    ) -> tuple[int, list[EndpointRecord]]:
        def matches_mode(endpoint: EndpointRecord) -> bool:
            if mode == "unscanned":
                return endpoint.semantic_source != "llm_source_analysis"
            if mode == "stale":
                return endpoint.semantic_stale
            if mode == "low-confidence":
                return (
                    endpoint.semantic_source == "llm_source_analysis"
                    and not endpoint.semantic_stale
                    and endpoint.semantic_confidence <= max_confidence
                )
            if mode == "all":
                return (
                    endpoint.semantic_source != "llm_source_analysis"
                    or endpoint.semantic_confidence <= max_confidence
                    or endpoint.semantic_stale
                )
            raise ValueError(f"unsupported_semantic_queue_mode:{mode}")

        pending = [
            endpoint
            for endpoint in self._items.values()
            if endpoint.active
            if (project is None or endpoint.project == project)
            and (not services or endpoint.service in services)
            and matches_mode(endpoint)
        ]
        pending.sort(key=lambda endpoint: (endpoint.semantic_confidence, endpoint.updated_at))
        return len(pending), pending[:limit]

    def candidates(
        self,
        *,
        workspace_id: str = "",
        query: str,
        query_embedding: list[float],
        exact_identifiers: list[str],
        filters: SearchFilters,
        limit: int,
        soft_audiences: list[str] | None = None,
        soft_domains: list[str] | None = None,
        soft_actions: list[str] | None = None,
        soft_services: list[str] | None = None,
        soft_resource: str = "",
        soft_lookup_keys: list[str] | None = None,
        soft_identifier_types: list[str] | None = None,
        soft_cardinality: str = "unknown",
        soft_field_identifiers: list[str] | None = None,
        schema_direction: str = "unknown",
    ) -> list[Candidate]:
        query_tokens = set(tokenize(query))
        results: list[Candidate] = []
        for endpoint in self._items.values():
            if not endpoint.active:
                continue
            if workspace_id and endpoint.workspace_id != workspace_id:
                continue
            if filters.projects and endpoint.project not in filters.projects:
                continue
            if filters.services and endpoint.service not in filters.services:
                continue
            if filters.methods and endpoint.method not in filters.methods:
                continue
            if filters.audiences and not set(filters.audiences) & set(endpoint.audiences):
                continue
            if filters.domains and not set(filters.domains) & set(endpoint.domains):
                continue
            if filters.actions and not set(filters.actions) & set(endpoint.actions):
                continue
            if filters.resources and endpoint.resource not in filters.resources:
                continue
            if filters.lookup_keys and not set(filters.lookup_keys) & set(endpoint.lookup_keys):
                continue
            if filters.cardinalities and endpoint.cardinality not in filters.cardinalities:
                continue
            document_tokens = set(tokenize(endpoint.search_document))
            overlap = len(query_tokens & document_tokens) / max(1, len(query_tokens))
            schema_tokens = set(
                tokenize(
                    json.dumps(
                        {
                            "request": [
                                item.model_dump() for item in endpoint.request_schema_paths
                            ],
                            "response": [
                                item.model_dump() for item in endpoint.response_schema_paths
                            ],
                            "identifiers": [
                                item.model_dump() for item in endpoint.business_identifiers
                            ],
                        },
                        ensure_ascii=False,
                    )
                )
            )
            schema_overlap = len(query_tokens & schema_tokens) / max(1, len(query_tokens))
            exact = _exact_score(endpoint, query, exact_identifiers)
            vector = cosine_similarity(endpoint.embedding, query_embedding)
            structured = _structured_recall_score(
                endpoint,
                audiences=soft_audiences or [],
                domains=soft_domains or [],
                actions=soft_actions or [],
                services=soft_services or [],
                resource=soft_resource,
                lookup_keys=soft_lookup_keys or [],
                identifier_types=soft_identifier_types or [],
                cardinality=soft_cardinality,
            )
            family = _family_recall_score(endpoint, query)
            identifier = _identifier_recall_score(
                endpoint,
                resource=soft_resource,
                identifier_types=soft_identifier_types or [],
            )
            service_score = float(bool(soft_services and endpoint.service in soft_services))
            field_score = _field_recall_score(
                endpoint,
                soft_field_identifiers or [],
                schema_direction=schema_direction,
            )
            results.append(
                Candidate(
                    endpoint=endpoint,
                    lexical_score=overlap,
                    vector_score=vector,
                    exact_score=exact,
                    schema_recall_score=schema_overlap,
                    structured_recall_score=structured,
                    family_recall_score=family,
                    identifier_recall_score=identifier,
                    service_recall_score=service_score,
                    field_recall_score=field_score,
                )
            )
        results.sort(
            key=lambda item: (
                max(
                    item.exact_score,
                    item.lexical_score,
                    item.vector_score,
                    item.schema_recall_score,
                    item.structured_recall_score,
                    item.family_recall_score,
                    item.identifier_recall_score,
                    item.service_recall_score,
                    item.field_recall_score,
                ),
                item.field_recall_score,
                item.structured_recall_score,
                item.lexical_score,
                item.endpoint.id,
            ),
            reverse=True,
        )
        return results[:limit]

    def save_search_session(
        self, response: SearchResponse, filters: SearchFilters, *, ttl_days: int
    ) -> None:
        self._search_sessions[response.search_id] = response

    def get_search_session(self, search_id: str) -> SearchResponse | None:
        return self._search_sessions.get(search_id)

    def delete_expired_search_sessions(self) -> int:
        return 0

    def mark_unseen_inactive(
        self, project: str, seen_ids: list[str], *, workspace_id: str = ""
    ) -> int:
        seen = set(seen_ids)
        changed = 0
        for interface_id, endpoint in list(self._items.items()):
            if (
                endpoint.project == project
                and (not workspace_id or endpoint.workspace_id == workspace_id)
                and interface_id not in seen
                and endpoint.active
            ):
                self._items[interface_id] = endpoint.model_copy(update={"active": False})
                changed += 1
        return changed

    def rebuild_interface_families(self) -> int:
        groups = _group_endpoint_families(list(self._items.values()))
        changed = 0
        for endpoints in groups.values():
            for endpoint in endpoints:
                sibling_actions = _sibling_actions(endpoint, endpoints)
                updated = endpoint.model_copy(
                    update={
                        "sibling_actions": sibling_actions,
                        "family_size": len(endpoints),
                    }
                )
                changed += int(
                    endpoint.sibling_actions != sibling_actions
                    or endpoint.family_size != len(endpoints)
                )
                self._items[endpoint.id] = updated
        return changed


class PostgresEndpointRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self) -> psycopg.Connection:
        connection = psycopg.connect(self.database_url, row_factory=dict_row)
        register_vector(connection)
        return connection

    def count(self) -> int:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) AS count FROM interface_semantic_index WHERE active")
            return int(cursor.fetchone()["count"])

    def list_workspaces(self) -> list[WorkspaceProfile]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id FROM interface_search_workspaces WHERE active ORDER BY id")
            workspace_ids = [row["id"] for row in cursor.fetchall()]
        return [
            profile
            for workspace_id in workspace_ids
            if (profile := self.get_workspace_profile(workspace_id)) is not None
        ]

    def get_workspace_profile(self, workspace_id: str) -> WorkspaceProfile | None:
        if not workspace_id:
            return None
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM interface_search_workspaces WHERE id = %s AND active",
                (workspace_id,),
            )
            workspace = cursor.fetchone()
            if not workspace:
                return None
            cursor.execute(
                "SELECT * FROM interface_search_workspace_terms "
                "WHERE workspace_id = %s AND active ORDER BY priority DESC, id",
                (workspace_id,),
            )
            rows = cursor.fetchall()
        return WorkspaceProfile(
            workspace_id=workspace["id"],
            name=workspace["name"],
            source_root=workspace["source_root"],
            semantic_profile_version=workspace["semantic_profile_version"],
            metadata=workspace["metadata"],
            terms=[
                WorkspaceTerm(
                    dimension=row["dimension"],
                    canonical_value=row["canonical_value"],
                    aliases=row["aliases"],
                    mapped_values=row["mapped_values"],
                    metadata=row["metadata"],
                    priority=row["priority"],
                    source=row["source"],
                    confidence=row["confidence"],
                    active=row["active"],
                )
                for row in rows
            ],
        )

    def save_workspace_profile(self, profile: WorkspaceProfile) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO interface_search_workspaces
                    (id, name, source_root, semantic_profile_version, metadata, active)
                VALUES (%s, %s, %s, %s, %s::jsonb, TRUE)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    source_root = EXCLUDED.source_root,
                    semantic_profile_version = EXCLUDED.semantic_profile_version,
                    metadata = EXCLUDED.metadata,
                    active = TRUE,
                    updated_at = now()
                """,
                (
                    profile.workspace_id,
                    profile.name,
                    profile.source_root,
                    profile.semantic_profile_version,
                    json.dumps(profile.metadata, ensure_ascii=False),
                ),
            )
            for term in profile.terms:
                cursor.execute(
                    """
                    INSERT INTO interface_search_workspace_terms
                        (workspace_id, dimension, canonical_value, aliases, mapped_values,
                         metadata, priority, source, confidence, active)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
                    ON CONFLICT (workspace_id, dimension, canonical_value) DO UPDATE SET
                        aliases = EXCLUDED.aliases,
                        mapped_values = EXCLUDED.mapped_values,
                        metadata = EXCLUDED.metadata,
                        priority = EXCLUDED.priority,
                        source = EXCLUDED.source,
                        confidence = EXCLUDED.confidence,
                        active = EXCLUDED.active,
                        updated_at = now()
                    """,
                    (
                        profile.workspace_id,
                        term.dimension,
                        term.canonical_value,
                        term.aliases,
                        json.dumps(term.mapped_values, ensure_ascii=False),
                        json.dumps(term.metadata, ensure_ascii=False),
                        term.priority,
                        term.source,
                        term.confidence,
                        term.active,
                    ),
                )

    def add_many(self, endpoints: Iterable[EndpointRecord]) -> list[EndpointRecord]:
        pending = list(endpoints)
        if not pending:
            return []
        sql = """
            INSERT INTO interface_semantic_index (
                id, workspace_id, project, service, method, path, operation_id, title, purpose,
                audiences, domains, scenarios, actions, entities, aliases, tags,
                request_schema, response_schema, source_locations, search_document, embedding
                , semantic_source, semantic_model, semantic_confidence, semantic_evidence,
                contract_hash, contract_hash_version, semantic_stale, active, last_seen_at,
                resource, lookup_keys, cardinality, ownership, discriminators,
                required_inputs, search_document_zh, request_schema_paths,
                response_schema_paths, business_identifiers, semantic_field_sources,
                semantic_confidences, search_document_version, embedding_version
                , controller_name, interface_family, sibling_actions,
                distinguishing_features, family_size
            ) VALUES (
                %(id)s, %(workspace_id)s, %(project)s, %(service)s, %(method)s, %(path)s, %(operation_id)s,
                %(title)s, %(purpose)s, %(audiences)s, %(domains)s, %(scenarios)s,
                %(actions)s, %(entities)s, %(aliases)s, %(tags)s, %(request_schema)s::jsonb,
                %(response_schema)s::jsonb, %(source_locations)s, %(search_document)s,
                %(embedding)s, %(semantic_source)s, %(semantic_model)s,
                %(semantic_confidence)s, %(semantic_evidence)s,
                %(contract_hash)s, %(contract_hash_version)s, %(semantic_stale)s,
                TRUE, now(), %(resource)s, %(lookup_keys)s, %(cardinality)s,
                %(ownership)s, %(discriminators)s, %(required_inputs)s::jsonb,
                %(search_document_zh)s, %(request_schema_paths)s::jsonb,
                %(response_schema_paths)s::jsonb, %(business_identifiers)s::jsonb,
                %(semantic_field_sources)s::jsonb, %(semantic_confidences)s::jsonb,
                %(search_document_version)s, %(embedding_version)s
                , %(controller_name)s, %(interface_family)s, %(sibling_actions)s::jsonb,
                %(distinguishing_features)s::jsonb, %(family_size)s
            )
            ON CONFLICT (id) DO UPDATE SET
                workspace_id = EXCLUDED.workspace_id,
                project = EXCLUDED.project,
                service = CASE
                    WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                        AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.service
                    ELSE EXCLUDED.service END,
                method = EXCLUDED.method,
                path = EXCLUDED.path,
                operation_id = EXCLUDED.operation_id,
                title = EXCLUDED.title,
                purpose = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.purpose ELSE EXCLUDED.purpose END,
                audiences = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.audiences ELSE EXCLUDED.audiences END,
                domains = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.domains ELSE EXCLUDED.domains END,
                scenarios = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.scenarios ELSE EXCLUDED.scenarios END,
                actions = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.actions ELSE EXCLUDED.actions END,
                entities = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.entities ELSE EXCLUDED.entities END,
                aliases = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.aliases ELSE EXCLUDED.aliases END,
                resource = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.resource ELSE EXCLUDED.resource END,
                lookup_keys = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.lookup_keys ELSE EXCLUDED.lookup_keys END,
                cardinality = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.cardinality ELSE EXCLUDED.cardinality END,
                ownership = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.ownership ELSE EXCLUDED.ownership END,
                discriminators = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.discriminators ELSE EXCLUDED.discriminators END,
                required_inputs = EXCLUDED.required_inputs,
                request_schema_paths = EXCLUDED.request_schema_paths,
                response_schema_paths = EXCLUDED.response_schema_paths,
                business_identifiers = CASE
                    WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                        AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.business_identifiers
                    ELSE EXCLUDED.business_identifiers END,
                semantic_field_sources = CASE
                    WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                        AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.semantic_field_sources
                    ELSE EXCLUDED.semantic_field_sources END,
                semantic_confidences = CASE
                    WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                        AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.semantic_confidences
                    ELSE EXCLUDED.semantic_confidences END,
                search_document_version = EXCLUDED.search_document_version,
                embedding_version = EXCLUDED.embedding_version,
                controller_name = EXCLUDED.controller_name,
                interface_family = CASE
                    WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                        AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.interface_family
                    ELSE EXCLUDED.interface_family END,
                sibling_actions = EXCLUDED.sibling_actions,
                distinguishing_features = CASE
                    WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                        AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.distinguishing_features
                    ELSE EXCLUDED.distinguishing_features END,
                family_size = EXCLUDED.family_size,
                tags = EXCLUDED.tags,
                request_schema = EXCLUDED.request_schema,
                response_schema = EXCLUDED.response_schema,
                source_locations = EXCLUDED.source_locations,
                search_document = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.search_document ELSE EXCLUDED.search_document END,
                search_document_zh = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.search_document_zh ELSE EXCLUDED.search_document_zh END,
                embedding = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.embedding ELSE EXCLUDED.embedding END,
                semantic_source = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.semantic_source ELSE EXCLUDED.semantic_source END,
                semantic_model = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.semantic_model ELSE EXCLUDED.semantic_model END,
                semantic_confidence = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.semantic_confidence ELSE EXCLUDED.semantic_confidence END,
                semantic_evidence = CASE WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                    AND EXCLUDED.semantic_source <> 'llm_source_analysis'
                    THEN interface_semantic_index.semantic_evidence ELSE EXCLUDED.semantic_evidence END,
                semantic_stale = CASE
                    WHEN EXCLUDED.semantic_source = 'llm_source_analysis' THEN FALSE
                    WHEN interface_semantic_index.semantic_source = 'llm_source_analysis'
                        AND interface_semantic_index.contract_hash <> ''
                        AND interface_semantic_index.contract_hash_version = EXCLUDED.contract_hash_version
                        AND interface_semantic_index.contract_hash <> EXCLUDED.contract_hash THEN TRUE
                    ELSE interface_semantic_index.semantic_stale
                END,
                contract_hash = EXCLUDED.contract_hash,
                contract_hash_version = EXCLUDED.contract_hash_version,
                active = TRUE,
                last_seen_at = now(),
                updated_at = now()
            RETURNING *
        """
        saved: list[EndpointRecord] = []
        with self._connect() as connection, connection.cursor() as cursor:
            for endpoint in pending:
                row = endpoint.model_dump()
                row["request_schema"] = json.dumps(row["request_schema"], ensure_ascii=False)
                row["response_schema"] = json.dumps(row["response_schema"], ensure_ascii=False)
                row["required_inputs"] = json.dumps(row["required_inputs"], ensure_ascii=False)
                row["request_schema_paths"] = json.dumps(
                    row["request_schema_paths"], ensure_ascii=False
                )
                row["response_schema_paths"] = json.dumps(
                    row["response_schema_paths"], ensure_ascii=False
                )
                row["business_identifiers"] = json.dumps(
                    row["business_identifiers"], ensure_ascii=False
                )
                row["semantic_field_sources"] = json.dumps(
                    row["semantic_field_sources"], ensure_ascii=False
                )
                row["semantic_confidences"] = json.dumps(
                    row["semantic_confidences"], ensure_ascii=False
                )
                row["sibling_actions"] = json.dumps(row["sibling_actions"], ensure_ascii=False)
                row["distinguishing_features"] = json.dumps(
                    row["distinguishing_features"], ensure_ascii=False
                )
                cursor.execute(sql, row)
                saved.append(_row_to_endpoint(cursor.fetchone()))
        return saved

    def get(self, endpoint_id: str) -> EndpointRecord | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM interface_semantic_index WHERE id = %s", (endpoint_id,))
            row = cursor.fetchone()
        return _row_to_endpoint(row) if row else None

    def list_interfaces(
        self,
        *,
        workspace_id: str = "",
        query: str,
        service: str | None,
        method: str | None,
        semantic_status: str,
        offset: int,
        limit: int,
    ) -> tuple[int, list[EndpointRecord]]:
        where = """
            active
            AND (%(workspace_id)s = '' OR workspace_id = %(workspace_id)s)
            AND (%(query)s = '' OR search_document ILIKE '%%' || %(query)s || '%%'
                OR path ILIKE '%%' || %(query)s || '%%'
                OR operation_id ILIKE '%%' || %(query)s || '%%')
            AND (%(service)s::text IS NULL OR service ILIKE '%%' || %(service)s::text || '%%')
            AND (%(method)s::text IS NULL OR method = %(method)s::text)
            AND (
                %(semantic_status)s = 'all'
                OR (%(semantic_status)s = 'llm' AND semantic_source = 'llm_source_analysis')
                OR (%(semantic_status)s = 'bootstrap' AND semantic_source <> 'llm_source_analysis')
            )
        """
        params = {
            "workspace_id": workspace_id,
            "query": query.strip(),
            "service": service.strip() if service else None,
            "method": method,
            "semantic_status": semantic_status,
            "offset": offset,
            "limit": limit,
        }
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT count(*) AS count FROM interface_semantic_index WHERE {where}", params
            )
            total = int(cursor.fetchone()["count"])
            cursor.execute(
                f"""
                SELECT * FROM interface_semantic_index
                WHERE {where}
                ORDER BY
                    CASE WHEN semantic_source = 'llm_source_analysis' THEN 0 ELSE 1 END,
                    updated_at DESC,
                    path ASC,
                    id ASC
                OFFSET %(offset)s LIMIT %(limit)s
                """,
                params,
            )
            rows = cursor.fetchall()
        return total, [_row_to_endpoint(row) for row in rows]

    def record_feedback(self, payload: dict) -> None:
        sql = """
            INSERT INTO interface_search_feedback (
                search_id, query, selected_interface_id, expected_interface_id,
                relevant, result_ranking, note
            ) VALUES (
                %(search_id)s, %(query)s, %(selected_interface_id)s,
                %(expected_interface_id)s, %(relevant)s, %(result_ranking)s::jsonb, %(note)s
            )
        """
        values = dict(payload)
        values["result_ranking"] = json.dumps(values["result_ranking"], ensure_ascii=False)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(sql, values)

    def feedback_count(self) -> int:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) AS count FROM interface_search_feedback")
            return int(cursor.fetchone()["count"])

    def semantic_queue(
        self,
        *,
        project: str | None,
        max_confidence: float,
        limit: int,
        services: list[str] | None = None,
        mode: SemanticQueueMode = "all",
    ) -> tuple[int, list[EndpointRecord]]:
        mode_conditions = {
            "all": "(semantic_source <> 'llm_source_analysis' OR semantic_confidence <= %(max_confidence)s OR semantic_stale)",
            "unscanned": "semantic_source <> 'llm_source_analysis'",
            "stale": "semantic_stale",
            "low-confidence": "(semantic_source = 'llm_source_analysis' AND NOT semantic_stale AND semantic_confidence <= %(max_confidence)s)",
        }
        try:
            mode_condition = mode_conditions[mode]
        except KeyError as exc:
            raise ValueError(f"unsupported_semantic_queue_mode:{mode}") from exc
        where = f"""
            (%(project)s::text IS NULL OR project = %(project)s::text)
            AND (%(services)s::text[] IS NULL OR service = ANY(%(services)s::text[]))
            AND active
            AND {mode_condition}
        """
        params = {
            "project": project,
            "services": services or None,
            "max_confidence": max_confidence,
            "limit": limit,
        }
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT count(*) AS count FROM interface_semantic_index WHERE {where}", params
            )
            total = int(cursor.fetchone()["count"])
            cursor.execute(
                f"""
                SELECT * FROM interface_semantic_index
                WHERE {where}
                ORDER BY semantic_confidence ASC, updated_at ASC, id ASC
                LIMIT %(limit)s
                """,
                params,
            )
            rows = cursor.fetchall()
        return total, [_row_to_endpoint(row) for row in rows]

    def candidates(
        self,
        *,
        workspace_id: str = "",
        query: str,
        query_embedding: list[float],
        exact_identifiers: list[str],
        filters: SearchFilters,
        limit: int,
        soft_audiences: list[str] | None = None,
        soft_domains: list[str] | None = None,
        soft_actions: list[str] | None = None,
        soft_services: list[str] | None = None,
        soft_resource: str = "",
        soft_lookup_keys: list[str] | None = None,
        soft_identifier_types: list[str] | None = None,
        soft_cardinality: str = "unknown",
        soft_field_identifiers: list[str] | None = None,
        schema_direction: str = "unknown",
    ) -> list[Candidate]:
        sql = """
            WITH scored AS (
                SELECT e.*,
                    greatest(
                        ts_rank_cd(
                            e.search_tsvector_zh,
                            websearch_to_tsquery('simple', %(lexical_query)s),
                            32
                        ),
                        ts_rank_cd(e.search_tsvector, websearch_to_tsquery('simple', %(query)s), 32),
                        similarity(e.search_document, %(query)s)
                    ) AS lexical_score,
                    CASE WHEN e.embedding IS NULL THEN 0
                         ELSE 1 - (e.embedding <=> %(embedding)s) END AS vector_score,
                    greatest(
                        similarity(e.request_schema_paths::text, %(query)s),
                        similarity(e.response_schema_paths::text, %(query)s),
                        similarity(e.business_identifiers::text, %(query)s)
                    ) AS schema_recall_score,
                    CASE
                        WHEN %(soft_field_identifiers)s::text[] = '{}' THEN 0
                        WHEN %(schema_direction)s = 'request' AND EXISTS (
                            SELECT 1 FROM jsonb_array_elements(e.request_schema_paths) field
                            WHERE regexp_replace(
                                lower(coalesce(nullif(field->>'normalized_name', ''),
                                    regexp_replace(field->>'path', '^.*\\.', ''))),
                                '[^a-z0-9]', '', 'g'
                            ) = ANY(%(soft_field_identifiers)s::text[])
                        ) THEN 1.0
                        WHEN %(schema_direction)s = 'response' AND EXISTS (
                            SELECT 1 FROM jsonb_array_elements(e.response_schema_paths) field
                            WHERE regexp_replace(
                                lower(coalesce(nullif(field->>'normalized_name', ''),
                                    regexp_replace(field->>'path', '^.*\\.', ''))),
                                '[^a-z0-9]', '', 'g'
                            ) = ANY(%(soft_field_identifiers)s::text[])
                        ) THEN 1.0
                        WHEN EXISTS (
                            SELECT 1 FROM jsonb_array_elements(e.request_schema_paths) field
                            WHERE regexp_replace(
                                lower(coalesce(nullif(field->>'normalized_name', ''),
                                    regexp_replace(field->>'path', '^.*\\.', ''))),
                                '[^a-z0-9]', '', 'g'
                            ) = ANY(%(soft_field_identifiers)s::text[])
                        ) OR EXISTS (
                            SELECT 1 FROM jsonb_array_elements(e.response_schema_paths) field
                            WHERE regexp_replace(
                                lower(coalesce(nullif(field->>'normalized_name', ''),
                                    regexp_replace(field->>'path', '^.*\\.', ''))),
                                '[^a-z0-9]', '', 'g'
                            ) = ANY(%(soft_field_identifiers)s::text[])
                        ) THEN CASE WHEN %(schema_direction)s = 'unknown' THEN 0.72 ELSE 0.12 END
                        ELSE 0
                    END AS field_recall_score,
                    CASE
                        WHEN %(soft_identifier_types)s::text[] <> '{}'
                            AND e.lookup_keys && %(soft_identifier_types)s::text[]
                            AND (%(soft_resource)s = '' OR e.resource = %(soft_resource)s)
                            THEN 1.0
                        WHEN %(soft_identifier_types)s::text[] <> '{}'
                            AND e.lookup_keys && %(soft_identifier_types)s::text[]
                            THEN 0.45
                        ELSE 0
                    END AS identifier_recall_score,
                    CASE WHEN %(soft_services)s::text[] <> '{}'
                        AND e.service = ANY(%(soft_services)s::text[]) THEN 1.0 ELSE 0
                    END AS service_recall_score,
                    (
                        CASE WHEN %(soft_resource)s <> '' AND e.resource = %(soft_resource)s
                            THEN 0.30 ELSE 0 END
                        + CASE WHEN %(soft_audiences)s::text[] <> '{}'
                            AND e.audiences && %(soft_audiences)s::text[] THEN 0.20 ELSE 0 END
                        + CASE WHEN %(soft_domains)s::text[] <> '{}'
                            AND e.domains && %(soft_domains)s::text[] THEN 0.15 ELSE 0 END
                        + CASE WHEN %(soft_actions)s::text[] <> '{}'
                            AND e.actions && %(soft_actions)s::text[] THEN 0.20 ELSE 0 END
                        + CASE WHEN %(soft_lookup_keys)s::text[] <> '{}'
                            AND e.lookup_keys && %(soft_lookup_keys)s::text[] THEN 0.10 ELSE 0 END
                        + CASE WHEN %(soft_cardinality)s <> 'unknown'
                            AND e.cardinality = %(soft_cardinality)s THEN 0.05 ELSE 0 END
                        + CASE WHEN %(soft_services)s::text[] <> '{}'
                            AND e.service = ANY(%(soft_services)s::text[]) THEN 0.10 ELSE 0 END
                    ) AS structured_recall_score,
                    CASE
                        WHEN e.interface_family <> ''
                            AND lower(%(raw_query)s) LIKE '%%' || lower(e.interface_family) || '%%'
                            AND (
                                position('_' in e.interface_family) > 0
                                OR position('-' in e.interface_family) > 0
                                OR lower(%(raw_query)s) LIKE '%%家族%%'
                                OR lower(%(raw_query)s) LIKE '%%' || lower(e.interface_family) || '接口%%'
                            )
                            THEN 1.0
                        WHEN e.controller_name <> ''
                            AND lower(%(raw_query)s) LIKE '%%' || lower(e.controller_name) || '%%'
                            THEN 0.95
                        ELSE 0
                    END AS family_recall_score,
                    CASE
                        WHEN lower(e.path) = lower(%(raw_query)s) THEN 1.0
                        WHEN lower(e.path) = ANY(%(exact_identifiers)s) THEN 1.0
                        WHEN lower(e.operation_id) = lower(%(raw_query)s) THEN 0.95
                        WHEN lower(e.operation_id) = ANY(%(exact_identifiers)s) THEN 0.95
                        WHEN EXISTS (
                            SELECT 1 FROM unnest(e.aliases) alias
                            WHERE lower(alias) = lower(%(raw_query)s)
                               OR lower(alias) = ANY(%(exact_identifiers)s)
                        ) THEN 0.92
                        WHEN EXISTS (
                            SELECT 1 FROM unnest(%(exact_identifiers)s::text[]) identifier
                            WHERE lower(e.path) LIKE '%%' || identifier
                               OR lower(e.operation_id) LIKE '%%.' || identifier
                        ) THEN 0.88
                        WHEN lower(e.path) LIKE '%%' || lower(%(raw_query)s) || '%%' THEN 0.8
                        ELSE 0
                    END AS exact_score
                FROM interface_semantic_index e
                WHERE e.active
                  AND (%(workspace_id)s = '' OR e.workspace_id = %(workspace_id)s)
                  AND (%(projects)s::text[] = '{}' OR e.project = ANY(%(projects)s))
                  AND (%(services)s::text[] = '{}' OR e.service = ANY(%(services)s))
                  AND (%(methods)s::text[] = '{}' OR e.method = ANY(%(methods)s))
                  AND (%(audiences)s::text[] = '{}' OR e.audiences && %(audiences)s::text[])
                  AND (%(domains)s::text[] = '{}' OR e.domains && %(domains)s::text[])
                  AND (%(actions)s::text[] = '{}' OR e.actions && %(actions)s::text[])
                  AND (%(resources)s::text[] = '{}' OR e.resource = ANY(%(resources)s))
                  AND (%(lookup_keys)s::text[] = '{}' OR e.lookup_keys && %(lookup_keys)s::text[])
                  AND (%(cardinalities)s::text[] = '{}' OR e.cardinality = ANY(%(cardinalities)s))
            ), lexical_lane AS (
                SELECT id FROM scored ORDER BY greatest(exact_score, lexical_score) DESC LIMIT %(limit)s
            ), vector_lane AS (
                SELECT id FROM scored ORDER BY vector_score DESC LIMIT %(limit)s
            ), schema_lane AS (
                SELECT id FROM scored ORDER BY schema_recall_score DESC LIMIT %(limit)s
            ), field_lane AS (
                SELECT id FROM scored
                WHERE field_recall_score > 0
                ORDER BY field_recall_score DESC, structured_recall_score DESC,
                    lexical_score DESC
                LIMIT %(limit)s
            ), structured_lane AS (
                SELECT id FROM scored ORDER BY structured_recall_score DESC LIMIT %(limit)s
            ), lookup_lane AS (
                SELECT id FROM scored
                WHERE %(soft_lookup_keys)s::text[] <> '{}'
                  AND lookup_keys && %(soft_lookup_keys)s::text[]
                ORDER BY lexical_score DESC
                LIMIT %(limit)s
            ), identifier_lane AS (
                SELECT id FROM scored
                WHERE identifier_recall_score > 0
                ORDER BY identifier_recall_score DESC, structured_recall_score DESC
                LIMIT %(limit)s
            ), service_lane AS (
                SELECT id FROM scored
                WHERE service_recall_score > 0
                ORDER BY service_recall_score DESC, lexical_score DESC
                LIMIT %(limit)s
            ), family_lane AS (
                SELECT id FROM scored
                WHERE family_recall_score > 0
                ORDER BY family_recall_score DESC, structured_recall_score DESC
                LIMIT %(limit)s
            )
            SELECT scored.* FROM scored
            WHERE id IN (
                SELECT id FROM lexical_lane
                UNION SELECT id FROM vector_lane
                UNION SELECT id FROM schema_lane
                UNION SELECT id FROM field_lane
                UNION SELECT id FROM structured_lane
                UNION SELECT id FROM lookup_lane
                UNION SELECT id FROM identifier_lane
                UNION SELECT id FROM service_lane
                UNION SELECT id FROM family_lane
            )
        """
        params = {
            "workspace_id": workspace_id,
            "query": query,
            "lexical_query": " OR ".join(dict.fromkeys(tokenize(query))) or query,
            "raw_query": query.strip(),
            "exact_identifiers": [item.lower() for item in exact_identifiers],
            "embedding": Vector(query_embedding),
            "projects": filters.projects,
            "services": filters.services,
            "methods": filters.methods,
            "audiences": filters.audiences,
            "domains": filters.domains,
            "actions": filters.actions,
            "resources": filters.resources,
            "lookup_keys": filters.lookup_keys,
            "cardinalities": filters.cardinalities,
            "soft_audiences": soft_audiences or [],
            "soft_domains": soft_domains or [],
            "soft_actions": soft_actions or [],
            "soft_services": soft_services or [],
            "soft_resource": soft_resource,
            "soft_lookup_keys": soft_lookup_keys or [],
            "soft_identifier_types": soft_identifier_types or [],
            "soft_cardinality": soft_cardinality,
            "soft_field_identifiers": [
                _normalize_field_identifier(value)
                for value in (soft_field_identifiers or [])
                if _normalize_field_identifier(value)
            ],
            "schema_direction": schema_direction,
            "limit": limit,
        }
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        return [
            Candidate(
                _row_to_endpoint(row),
                float(row["lexical_score"] or 0),
                float(row["vector_score"] or 0),
                float(row["exact_score"] or 0),
                float(row["schema_recall_score"] or 0),
                float(row["structured_recall_score"] or 0),
                float(row["family_recall_score"] or 0),
                float(row["identifier_recall_score"] or 0),
                float(row["service_recall_score"] or 0),
                float(row["field_recall_score"] or 0),
            )
            for row in rows
        ]

    def save_search_session(
        self, response: SearchResponse, filters: SearchFilters, *, ttl_days: int
    ) -> None:
        sql = """
            INSERT INTO interface_search_sessions (search_id, query, filters, response, expires_at)
            VALUES (%s, %s, %s::jsonb, %s::jsonb, now() + make_interval(days => %s))
            ON CONFLICT (search_id) DO UPDATE SET
                filters = EXCLUDED.filters,
                response = EXCLUDED.response,
                expires_at = EXCLUDED.expires_at
        """
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    response.search_id,
                    response.query,
                    json.dumps(filters.model_dump(mode="json"), ensure_ascii=False),
                    json.dumps(response.model_dump(mode="json"), ensure_ascii=False),
                    ttl_days,
                ),
            )

    def get_search_session(self, search_id: str) -> SearchResponse | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT response FROM interface_search_sessions WHERE search_id = %s AND expires_at > now()",
                (search_id,),
            )
            row = cursor.fetchone()
        return SearchResponse.model_validate(row["response"]) if row else None

    def delete_expired_search_sessions(self) -> int:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM interface_search_sessions WHERE expires_at <= now()")
            return cursor.rowcount

    def mark_unseen_inactive(
        self, project: str, seen_ids: list[str], *, workspace_id: str = ""
    ) -> int:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE interface_semantic_index
                SET active = FALSE, updated_at = now()
                WHERE project = %s
                  AND (%s = '' OR workspace_id = %s)
                  AND active AND NOT (id = ANY(%s::uuid[]))
                """,
                (project, workspace_id, workspace_id, seen_ids),
            )
            return cursor.rowcount

    def rebuild_interface_families(self) -> int:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM interface_semantic_index WHERE active ORDER BY id")
            endpoints = [_row_to_endpoint(row) for row in cursor.fetchall()]
            groups = _group_endpoint_families(endpoints)
            changed = 0
            for family in groups.values():
                for endpoint in family:
                    sibling_actions = _sibling_actions(endpoint, family)
                    cursor.execute(
                        """
                        UPDATE interface_semantic_index
                        SET sibling_actions = %s::jsonb,
                            family_size = %s,
                            updated_at = CASE
                                WHEN sibling_actions IS DISTINCT FROM %s::jsonb
                                  OR family_size <> %s THEN now()
                                ELSE updated_at
                            END
                        WHERE id = %s
                        """,
                        (
                            json.dumps(sibling_actions, ensure_ascii=False),
                            len(family),
                            json.dumps(sibling_actions, ensure_ascii=False),
                            len(family),
                            endpoint.id,
                        ),
                    )
                    changed += cursor.rowcount
            return changed


def _row_to_endpoint(row: dict) -> EndpointRecord:
    fields = EndpointRecord.model_fields
    values = {key: row[key] for key in fields if key in row}
    if "id" in values:
        values["id"] = str(values["id"])
    if isinstance(values.get("embedding"), Vector):
        values["embedding"] = values["embedding"].to_list()
    return EndpointRecord.model_validate(values)


SEMANTIC_FIELDS = (
    "purpose",
    "audiences",
    "domains",
    "scenarios",
    "actions",
    "entities",
    "aliases",
    "resource",
    "lookup_keys",
    "cardinality",
    "ownership",
    "discriminators",
    "business_identifiers",
    "semantic_field_sources",
    "semantic_confidences",
    "interface_family",
    "distinguishing_features",
    "search_document",
    "search_document_zh",
    "embedding",
    "semantic_source",
    "semantic_model",
    "semantic_confidence",
    "semantic_evidence",
)


def _merge_endpoint(existing: EndpointRecord, incoming: EndpointRecord) -> EndpointRecord:
    now = datetime.now(UTC)
    values = incoming.model_dump()
    values.update({"id": existing.id, "created_at": existing.created_at, "updated_at": now})
    if incoming.semantic_source == "llm_source_analysis":
        values["semantic_stale"] = False
    elif existing.semantic_source == "llm_source_analysis":
        for field in SEMANTIC_FIELDS:
            values[field] = getattr(existing, field)
        values["semantic_stale"] = existing.semantic_stale or bool(
            existing.contract_hash
            and incoming.contract_hash
            and existing.contract_hash_version == incoming.contract_hash_version
            and existing.contract_hash != incoming.contract_hash
        )
    else:
        values["semantic_stale"] = existing.semantic_stale
    values["active"] = True
    values["last_seen_at"] = now
    return EndpointRecord.model_validate(values)


def _group_endpoint_families(
    endpoints: list[EndpointRecord],
) -> dict[tuple[str, str, str, str], list[EndpointRecord]]:
    groups: dict[tuple[str, str, str, str], list[EndpointRecord]] = {}
    for endpoint in endpoints:
        if not endpoint.active:
            continue
        family_key = endpoint.controller_name or endpoint.interface_family or endpoint.path
        groups.setdefault(
            (endpoint.workspace_id, endpoint.project, endpoint.service, family_key), []
        ).append(endpoint)
    return groups


def _sibling_actions(
    endpoint: EndpointRecord,
    family: list[EndpointRecord],
) -> dict[str, list[str]]:
    actions: dict[str, list[str]] = {}
    for sibling in family:
        if sibling.id == endpoint.id:
            continue
        for action in sibling_action_keys(sibling.actions):
            actions.setdefault(action, []).append(sibling.id)
    return {action: sorted(set(interface_ids)) for action, interface_ids in sorted(actions.items())}


def _exact_score(
    endpoint: EndpointRecord, query: str, exact_identifiers: list[str] | None = None
) -> float:
    lowered = query.strip().lower()
    identifiers = {item.lower() for item in (exact_identifiers or [])}
    if endpoint.path.lower() in identifiers:
        return 1.0
    if endpoint.operation_id.lower() in identifiers:
        return 0.95
    if identifiers & {alias.lower() for alias in endpoint.aliases}:
        return 0.92
    if any(
        endpoint.path.lower().endswith(identifier)
        or endpoint.operation_id.lower().endswith(f".{identifier}")
        for identifier in identifiers
    ):
        return 0.88
    if lowered in {endpoint.path.lower(), endpoint.operation_id.lower()}:
        return 1.0
    if lowered and lowered in endpoint.path.lower():
        return 0.84
    if lowered and any(lowered == alias.lower() for alias in endpoint.aliases):
        return 0.9
    return 0.0


def _structured_recall_score(
    endpoint: EndpointRecord,
    *,
    audiences: list[str],
    domains: list[str],
    actions: list[str],
    services: list[str],
    resource: str,
    lookup_keys: list[str],
    identifier_types: list[str],
    cardinality: str,
) -> float:
    return (
        (0.30 if resource and endpoint.resource == resource else 0)
        + (0.20 if set(audiences) & set(endpoint.audiences) else 0)
        + (0.15 if set(domains) & set(endpoint.domains) else 0)
        + (0.20 if set(actions) & set(endpoint.actions) else 0)
        + (0.10 if services and endpoint.service in services else 0)
        + (0.10 if set(lookup_keys) & set(endpoint.lookup_keys) else 0)
        + (0.10 if set(identifier_types) & set(endpoint.lookup_keys) else 0)
        + (0.05 if cardinality != "unknown" and endpoint.cardinality == cardinality else 0)
    )


def _identifier_recall_score(
    endpoint: EndpointRecord, *, resource: str, identifier_types: list[str]
) -> float:
    if not identifier_types:
        return 0.0
    if not set(identifier_types) & set(endpoint.lookup_keys):
        return 0.0
    if resource and endpoint.resource == resource:
        return 1.0
    return 0.45


def _field_recall_score(
    endpoint: EndpointRecord,
    field_identifiers: list[str],
    *,
    schema_direction: str,
) -> float:
    requested = {
        normalized
        for value in field_identifiers
        if (normalized := _normalize_field_identifier(value))
    }
    if not requested:
        return 0.0
    request_names = _schema_field_names(endpoint.request_schema_paths)
    response_names = _schema_field_names(endpoint.response_schema_paths)
    request_match = bool(requested & request_names)
    response_match = bool(requested & response_names)
    if schema_direction == "request":
        return 1.0 if request_match else (0.12 if response_match else 0.0)
    if schema_direction == "response":
        return 1.0 if response_match else (0.12 if request_match else 0.0)
    return 0.72 if request_match or response_match else 0.0


def _schema_field_names(fields: list) -> set[str]:
    values: set[str] = set()
    for field in fields:
        terminal = field.path.removesuffix("[]").rsplit(".", 1)[-1]
        values.update(
            value
            for source in (field.normalized_name, terminal)
            if (value := _normalize_field_identifier(source))
        )
    return values


def _normalize_field_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _family_recall_score(endpoint: EndpointRecord, query: str) -> float:
    normalized = query.strip().lower()
    family = endpoint.interface_family.lower()
    if family and family in normalized:
        explicit = (
            "_" in family
            or "-" in family
            or "家族" in normalized
            or f"{family}接口" in normalized
            or normalized == family
        )
        if explicit:
            return 1.0
    if endpoint.controller_name and endpoint.controller_name.lower() in normalized:
        return 0.95
    family_tokens = set(tokenize(endpoint.interface_family))
    query_tokens = set(tokenize(normalized))
    if family_tokens and family_tokens <= query_tokens:
        return 0.85
    return 0.0
