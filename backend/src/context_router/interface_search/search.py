from __future__ import annotations

import re
from dataclasses import dataclass, field
from time import perf_counter
from uuid import uuid4

from context_router.interface_search.config import Settings
from context_router.interface_search.contracts import (
    CONTRACT_HASH_VERSION,
    calculate_contract_hash,
    extract_schema_field_paths,
)
from context_router.interface_search.domain import (
    EndpointCreate,
    EndpointRecord,
    EndpointSemanticUpdate,
    SchemaFieldPath,
    ScoreBreakdown,
    SearchCandidateTrace,
    SearchExplanation,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SearchTrace,
)
from context_router.interface_search.embedding import (
    EmbeddingProvider,
    LocalFeatureEmbedding,
    tokenize,
)
from context_router.interface_search.families import (
    build_distinguishing_features,
    infer_controller_name,
    infer_interface_family,
)
from context_router.interface_search.query_understanding import understand_query
from context_router.interface_search.repository import Candidate, EndpointRepository
from context_router.interface_search.route_identity import (
    describe_endpoint_route,
    infer_endpoint_call_layer,
    infer_endpoint_route_signals,
    infer_query_call_layer,
    infer_query_route_signals,
    route_identity_score,
)
from context_router.interface_search.slots import (
    build_discriminators,
    infer_business_identifiers,
    infer_cardinality,
    infer_lookup_keys,
    infer_ownership,
    infer_required_inputs,
    infer_resource,
    lookup_keys_from_identifiers,
)
from context_router.interface_search.taxonomy import canonicalize_values, normalize_actions
from context_router.interface_search.workspaces import WorkspaceProfile


def build_search_document(endpoint: EndpointCreate) -> str:
    required_inputs = " ".join(
        f"{item.name} {item.zh_name} {item.location}"
        for item in endpoint.required_inputs
        if item.required
    )
    lines = (
        f"用途: {endpoint.purpose}",
        f"使用端: {' '.join(endpoint.audiences)}",
        f"业务域: {' '.join(endpoint.domains)}",
        f"资源: {endpoint.resource}",
        f"接口家族: {endpoint.interface_family}",
        f"控制器: {endpoint.controller_name}",
        f"动作: {' '.join(endpoint.actions)}",
        f"查找键: {' '.join(endpoint.lookup_keys)}",
        f"基数: {endpoint.cardinality}",
        f"归属: {endpoint.ownership}",
        f"区别: {' '.join(endpoint.discriminators)}",
        f"场景: {' '.join(endpoint.scenarios)}",
        f"实体: {' '.join(endpoint.entities)}",
        f"别名: {' '.join(endpoint.aliases)}",
        f"路径: {endpoint.path}",
        f"操作标识: {endpoint.operation_id}",
        f"必填入参: {required_inputs}",
        f"项目服务: {endpoint.project} {endpoint.service} {endpoint.method}",
        "路由身份: "
        + describe_endpoint_route(
            project=endpoint.project,
            service=endpoint.service,
            path=endpoint.path,
            operation_id=endpoint.operation_id,
            title=endpoint.title,
            actions=endpoint.actions,
        ),
        f"标签: {' '.join(endpoint.tags)}",
    )
    return "\n".join(line for line in lines if not line.endswith(": "))


def build_lexical_document(document: str) -> str:
    return " ".join(dict.fromkeys(tokenize(document)))


def build_query_document(intent) -> str:
    parts = [
        f"用途: {intent.positive_query or intent.normalized_query}",
        f"使用端: {' '.join(intent.audiences)}",
        f"业务域: {' '.join(intent.domains)}",
        f"目标资源: {intent.target_resource or intent.resource}",
        f"条件资源: {' '.join(intent.context_resources)}",
        f"动作: {' '.join(intent.actions)}",
        f"查找键: {' '.join(intent.lookup_keys)}",
        f"字段: {' '.join(intent.field_paths or intent.field_identifiers)}",
        f"字段方向: {intent.schema_direction}",
        f"基数: {intent.cardinality}",
        f"归属: {intent.ownership}",
        "排除: "
        + " ".join(
            f"{dimension}={'/'.join(values)}" for dimension, values in intent.negative_slots.items()
        ),
    ]
    return "\n".join(part for part in parts if not part.endswith(": "))


@dataclass
class RankedCandidate:
    candidate: Candidate
    breakdown: ScoreBreakdown
    reasons: list[str]
    matched_slots: list[str] = field(default_factory=list)
    conflicting_slots: list[str] = field(default_factory=list)


class SearchService:
    def __init__(
        self,
        repository: EndpointRepository,
        embedding_provider: EmbeddingProvider,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.settings = settings
        self.local_embedding = isinstance(embedding_provider, LocalFeatureEmbedding)
        self._searches: dict[str, SearchResponse] = {}
        self._workspace_profiles: dict[str, WorkspaceProfile | None] = {}

    def workspace_profile(self, workspace_id: str) -> WorkspaceProfile | None:
        if not workspace_id:
            return None
        if workspace_id not in self._workspace_profiles:
            self._workspace_profiles[workspace_id] = self.repository.get_workspace_profile(
                workspace_id
            )
        return self._workspace_profiles[workspace_id]

    def save_workspace_profile(self, profile: WorkspaceProfile) -> None:
        self.repository.save_workspace_profile(profile)
        self._workspace_profiles[profile.workspace_id] = profile

    def _resolve_workspace_id(self, requested: str, projects: list[str] | None = None) -> str:
        if requested:
            return requested
        if projects and len(projects) == 1:
            return projects[0]
        workspaces = self.repository.list_workspaces()
        return workspaces[0].workspace_id if len(workspaces) == 1 else ""

    def prepare(self, endpoint: EndpointCreate) -> EndpointRecord:
        workspace_id = endpoint.workspace_id or endpoint.project
        profile = self.workspace_profile(workspace_id)
        technical_text = " ".join(
            [
                endpoint.path,
                endpoint.operation_id,
                endpoint.title,
                endpoint.purpose,
                *endpoint.actions,
            ]
        )
        audiences = canonicalize_values(endpoint.audiences, "audience", profile=profile)
        domains = canonicalize_values(endpoint.domains, "domain", profile=profile)
        actions = (
            canonicalize_values(endpoint.actions, "action", profile=profile)
            if endpoint.actions and endpoint.semantic_source == "llm_source_analysis"
            else normalize_actions(endpoint.actions, technical_text, profile)
        )
        resource = endpoint.resource or infer_resource(technical_text, domains, profile)
        required_inputs = endpoint.required_inputs or infer_required_inputs(
            endpoint.request_schema, profile
        )
        request_schema_paths = endpoint.request_schema_paths or extract_schema_field_paths(
            endpoint.request_schema,
            default_location="body",
        )
        if not request_schema_paths and required_inputs:
            request_schema_paths = [
                SchemaFieldPath(
                    path=item.name,
                    normalized_name=item.name,
                    meaning=item.zh_name,
                    data_type=item.schema_type,
                    required=item.required,
                    location=item.location,
                    source="source_signature",
                    confidence=0.94,
                )
                for item in required_inputs
            ]
        response_schema_paths = endpoint.response_schema_paths or extract_schema_field_paths(
            endpoint.response_schema,
            default_location="response",
        )
        business_identifiers = endpoint.business_identifiers or infer_business_identifiers(
            resource=resource,
            request_fields=request_schema_paths,
            response_fields=response_schema_paths,
            required_inputs=required_inputs,
        )
        lookup_keys = list(
            dict.fromkeys(
                [
                    *endpoint.lookup_keys,
                    *infer_lookup_keys(technical_text, profile),
                    *lookup_keys_from_identifiers(business_identifiers),
                ]
            )
        )[:30]
        cardinality = (
            endpoint.cardinality
            if endpoint.cardinality != "unknown"
            else infer_cardinality(technical_text, actions)
        )
        ownership = (
            endpoint.ownership
            if endpoint.ownership != "unknown"
            else infer_ownership(technical_text)
        )
        discriminators = endpoint.discriminators or build_discriminators(
            audiences=audiences,
            actions=actions,
            lookup_keys=lookup_keys,
            cardinality=cardinality,
            ownership=ownership,
        )
        semantic_fields = (
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
        )
        semantic_field_sources = {
            **{field: endpoint.semantic_source for field in semantic_fields},
            "required_inputs": "exact_contract",
            "request_schema_paths": "exact_contract",
            "response_schema_paths": "exact_contract",
            "business_identifiers": "contract_inference",
            **endpoint.semantic_field_sources,
        }
        semantic_confidences = {
            **{field: endpoint.semantic_confidence for field in semantic_fields},
            "required_inputs": 0.97,
            "request_schema_paths": 0.95,
            "response_schema_paths": 0.9,
            "business_identifiers": 0.9,
            **endpoint.semantic_confidences,
        }
        endpoint = endpoint.model_copy(
            update={
                "workspace_id": workspace_id,
                "audiences": audiences,
                "domains": domains,
                "actions": actions,
                "resource": resource,
                "lookup_keys": lookup_keys,
                "cardinality": cardinality,
                "ownership": ownership,
                "discriminators": discriminators,
                "required_inputs": required_inputs,
                "request_schema_paths": request_schema_paths,
                "response_schema_paths": response_schema_paths,
                "business_identifiers": business_identifiers,
                "search_document_version": "v4",
                "semantic_field_sources": semantic_field_sources,
                "semantic_confidences": semantic_confidences,
            }
        )
        controller_name = endpoint.controller_name or infer_controller_name(endpoint.operation_id)
        interface_family = endpoint.interface_family or infer_interface_family(
            resource=endpoint.resource,
            controller_name=controller_name,
            path=endpoint.path,
        )
        endpoint = endpoint.model_copy(
            update={
                "controller_name": controller_name,
                "interface_family": interface_family,
                "distinguishing_features": endpoint.distinguishing_features
                or build_distinguishing_features(endpoint),
            }
        )
        document = build_search_document(endpoint)
        if profile:
            document = profile.expand_text(document, dimensions=("endpoint_alias",))
        vector = self.embedding_provider.embed([document])[0]
        record = EndpointRecord(
            **endpoint.model_dump(),
            search_document=document,
            search_document_zh=build_lexical_document(document),
            embedding=vector,
        )
        return record.model_copy(
            update={
                "contract_hash": calculate_contract_hash(record),
                "contract_hash_version": CONTRACT_HASH_VERSION,
            }
        )

    def add_many(self, endpoints: list[EndpointCreate]) -> list[EndpointRecord]:
        saved = self.repository.add_many(self.prepare(endpoint) for endpoint in endpoints)
        self.repository.rebuild_interface_families()
        if len(saved) <= 20:
            return [self.repository.get(endpoint.id) or endpoint for endpoint in saved]
        return saved

    def add_many_with_ids(
        self, endpoints: list[tuple[str, EndpointCreate]]
    ) -> list[EndpointRecord]:
        """Index host-owned interfaces without changing their executable IDs."""

        prepared = [
            self.prepare(endpoint).model_copy(update={"id": interface_id})
            for interface_id, endpoint in endpoints
        ]
        saved = self.repository.add_many(prepared)
        self.repository.rebuild_interface_families()
        if len(saved) <= 20:
            return [self.repository.get(endpoint.id) or endpoint for endpoint in saved]
        return saved

    def update_semantics(
        self,
        interface_id: str,
        update: EndpointSemanticUpdate,
        *,
        rebuild_families: bool = True,
    ) -> EndpointRecord | None:
        endpoint = self.repository.get(interface_id)
        if endpoint is None:
            return None
        provided_fields = update.model_fields_set
        profile = self.workspace_profile(endpoint.workspace_id)
        normalized_update = update.model_copy(
            update={
                "audiences": canonicalize_values(update.audiences, "audience", profile=profile),
                "domains": canonicalize_values(update.domains, "domain", profile=profile),
                "actions": (
                    canonicalize_values(update.actions, "action", profile=profile)
                    if "actions" in provided_fields
                    else normalize_actions(
                        update.actions,
                        " ".join(
                            [
                                endpoint.path,
                                endpoint.operation_id,
                                endpoint.title,
                                update.purpose,
                            ]
                        ),
                        profile,
                    )
                ),
            }
        )
        semantic_text = " ".join(
            [
                endpoint.path,
                endpoint.operation_id,
                endpoint.title,
                normalized_update.purpose,
                *normalized_update.actions,
            ]
        )
        required_inputs = (
            normalized_update.required_inputs
            if "required_inputs" in provided_fields
            else endpoint.required_inputs or infer_required_inputs(endpoint.request_schema, profile)
        )
        request_schema_paths = endpoint.request_schema_paths or extract_schema_field_paths(
            endpoint.request_schema,
            default_location="body",
        )
        response_schema_paths = endpoint.response_schema_paths or extract_schema_field_paths(
            endpoint.response_schema,
            default_location="response",
        )
        lookup_keys = (
            normalized_update.lookup_keys
            if "lookup_keys" in provided_fields
            else endpoint.lookup_keys or infer_lookup_keys(semantic_text, profile)
        )
        resource = (
            normalized_update.resource
            if "resource" in provided_fields
            else endpoint.resource
            or infer_resource(semantic_text, normalized_update.domains, profile)
        )
        business_identifiers = (
            normalized_update.business_identifiers
            if "business_identifiers" in provided_fields
            else None
        )
        if business_identifiers is None and endpoint.semantic_stale:
            business_identifiers = infer_business_identifiers(
                resource=resource,
                request_fields=request_schema_paths,
                response_fields=response_schema_paths,
                required_inputs=required_inputs,
            )
        if business_identifiers is None:
            business_identifiers = endpoint.business_identifiers or infer_business_identifiers(
                resource=resource,
                request_fields=request_schema_paths,
                response_fields=response_schema_paths,
                required_inputs=required_inputs,
            )
        lookup_keys = list(
            dict.fromkeys([*lookup_keys, *lookup_keys_from_identifiers(business_identifiers)])
        )[:30]
        cardinality = normalized_update.cardinality
        if "cardinality" not in provided_fields and cardinality == "unknown":
            cardinality = (
                endpoint.cardinality
                if endpoint.cardinality != "unknown"
                else infer_cardinality(semantic_text, normalized_update.actions)
            )
        ownership = normalized_update.ownership
        if "ownership" not in provided_fields and ownership == "unknown":
            ownership = (
                endpoint.ownership
                if endpoint.ownership != "unknown"
                else infer_ownership(semantic_text)
            )
        normalized_update = normalized_update.model_copy(
            update={
                "resource": resource,
                "lookup_keys": lookup_keys,
                "cardinality": cardinality,
                "ownership": ownership,
                "required_inputs": required_inputs,
                "business_identifiers": business_identifiers,
                "discriminators": (
                    normalized_update.discriminators
                    if "discriminators" in provided_fields
                    else endpoint.discriminators
                    or build_discriminators(
                        audiences=normalized_update.audiences,
                        actions=normalized_update.actions,
                        lookup_keys=lookup_keys,
                        cardinality=cardinality,
                        ownership=ownership,
                    )
                ),
            }
        )
        update_values = normalized_update.model_dump()
        update_values["required_inputs"] = normalized_update.required_inputs
        llm_fields = (
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
        )
        merged = EndpointRecord.model_validate(
            {
                **endpoint.model_dump(),
                **update_values,
                "request_schema_paths": request_schema_paths,
                "response_schema_paths": response_schema_paths,
                "business_identifiers": business_identifiers,
                "search_document_version": "v4",
                "semantic_field_sources": {
                    **endpoint.semantic_field_sources,
                    **{field: "llm_source_analysis" for field in llm_fields},
                },
                "semantic_confidences": {
                    **endpoint.semantic_confidences,
                    **{field: normalized_update.semantic_confidence for field in llm_fields},
                },
                "semantic_source": "llm_source_analysis",
                "semantic_stale": False,
            }
        )
        merged = merged.model_copy(
            update={
                "interface_family": infer_interface_family(
                    resource=merged.resource,
                    controller_name=merged.controller_name,
                    path=merged.path,
                ),
                "distinguishing_features": build_distinguishing_features(merged),
            }
        )
        document = build_search_document(merged)
        if profile:
            document = profile.expand_text(document, dimensions=("endpoint_alias",))
        vector = self.embedding_provider.embed([document])[0]
        merged = merged.model_copy(
            update={
                "search_document": document,
                "search_document_zh": build_lexical_document(document),
                "embedding": vector,
            }
        )
        saved = self.repository.add_many([merged])[0]
        if rebuild_families:
            self.repository.rebuild_interface_families()
        return self.repository.get(saved.id) or saved

    def search(self, request: SearchRequest) -> SearchResponse:
        started = perf_counter()
        search_id = str(uuid4())
        filters = request.filters.model_copy(deep=True)
        workspace_id = self._resolve_workspace_id(request.workspace_id, filters.projects)
        profile = self.workspace_profile(workspace_id)
        intent = understand_query(request.query, profile)
        filters.audiences = canonicalize_values(filters.audiences, "audience", profile=profile)
        filters.domains = canonicalize_values(filters.domains, "domain", profile=profile)
        filters.actions = canonicalize_values(filters.actions, "action", profile=profile)
        if intent.explicit_method and not filters.methods:
            filters.methods = [intent.explicit_method]
        query_document = build_query_document(intent)
        retrieval_query = intent.positive_query or intent.normalized_query
        if profile:
            query_document = profile.expand_text(query_document, dimensions=("endpoint_alias",))
            # Expand endpoint aliases exactly, then append only the canonical
            # slots selected by query understanding. Expanding every matching
            # resource alias can inject several mutually exclusive resources
            # (for example one shared "transport order" alias for three modes)
            # and falsely trigger exact interface-family recall.
            retrieval_query = " ".join(
                dict.fromkeys(
                    item
                    for item in [
                        profile.expand_text(retrieval_query, dimensions=("endpoint_alias",)),
                        *(intent.audiences or []),
                        *(intent.domains or []),
                        *(intent.actions or []),
                        intent.target_resource or intent.resource,
                        *(intent.lookup_keys or []),
                    ]
                    if item
                )
            )
        query_vector = self.embedding_provider.embed([query_document])[0]
        candidates = self.repository.candidates(
            workspace_id=workspace_id,
            query=retrieval_query,
            query_embedding=query_vector,
            exact_identifiers=intent.endpoint_identifiers,
            filters=filters,
            limit=self.settings.search_candidate_limit,
            soft_audiences=intent.audiences,
            soft_domains=intent.domains,
            soft_actions=intent.actions,
            soft_services=intent.service_hints,
            soft_resource=intent.resource,
            soft_lookup_keys=intent.lookup_keys,
            soft_identifier_types=intent.identifier_types,
            soft_cardinality=intent.cardinality,
            soft_field_identifiers=intent.field_identifiers,
            schema_direction=intent.schema_direction,
            semantic_query_terms=_distinctive_query_terms(intent.positive_query),
        )
        for candidate in candidates:
            endpoint = candidate.endpoint
            endpoint_actions = normalize_actions(
                endpoint.actions,
                " ".join(
                    (
                        endpoint.path,
                        endpoint.operation_id,
                        endpoint.title,
                        endpoint.purpose,
                    )
                ),
                profile,
            )
            if set(endpoint_actions) & set(intent.actions):
                candidate.structured_recall_score = max(
                    candidate.structured_recall_score,
                    0.2,
                )
            candidate.route_identity_recall_score = max(
                candidate.route_identity_recall_score,
                route_identity_score(
                    query=request.query,
                    project=endpoint.project,
                    service=endpoint.service,
                    path=endpoint.path,
                    operation_id=endpoint.operation_id,
                    title=endpoint.title,
                    actions=endpoint.actions,
                    semantic_terms=(
                        endpoint.purpose,
                        *endpoint.domains,
                        *endpoint.scenarios,
                        *endpoint.aliases,
                    ),
                ),
            )
        ranked = self._rank(candidates, intent, profile)
        retrieval_ranks = {
            item.candidate.endpoint.id: index for index, item in enumerate(ranked, start=1)
        }
        preview = ranked[: request.top_k]
        top_score = preview[0].breakdown.total if preview else 0.0
        top_margin = top_score - preview[1].breakdown.total if len(preview) > 1 else top_score
        should_clarify = False
        clarification_question = None
        resolution_status = "resolved" if preview else "no_candidate"
        clarification_reason = (
            "AI 候选模式只负责高召回；唯一选择由用户推荐接口或调用方 Agent 完成。"
            if preview
            else "没有召回候选接口。"
        )
        missing_slots: list[str] = []
        hits: list[SearchHit] = []
        for index, item in enumerate(ranked[: request.top_k], start=1):
            endpoint = item.candidate.endpoint
            reasons = list(item.reasons)
            hits.append(
                SearchHit(
                    rank=index,
                    retrieval_rank=retrieval_ranks[endpoint.id],
                    interface_id=endpoint.id,
                    workspace_id=endpoint.workspace_id,
                    project=endpoint.project,
                    service=endpoint.service,
                    method=endpoint.method,
                    path=endpoint.path,
                    operation_id=endpoint.operation_id,
                    primary_source_location=(
                        endpoint.source_locations[0] if endpoint.source_locations else None
                    ),
                    title=endpoint.title,
                    purpose=endpoint.purpose,
                    audiences=endpoint.audiences,
                    domains=endpoint.domains,
                    scenarios=endpoint.scenarios,
                    resource=endpoint.resource,
                    actions=endpoint.actions,
                    lookup_keys=endpoint.lookup_keys,
                    cardinality=endpoint.cardinality,
                    discriminators=endpoint.discriminators,
                    matched_slots=item.matched_slots,
                    conflicting_slots=item.conflicting_slots,
                    controller_name=endpoint.controller_name,
                    interface_family=endpoint.interface_family,
                    family_size=endpoint.family_size,
                    sibling_actions=endpoint.sibling_actions,
                    semantic_stale=endpoint.semantic_stale,
                    confidence=item.breakdown.total,
                    score=item.breakdown,
                    reasons=reasons,
                )
            )
        confidence = "high" if top_score >= 0.78 and top_margin >= 0.10 else "medium"
        if hits and hits[0].semantic_stale and confidence == "high":
            confidence = "medium"
        response = SearchResponse(
            search_id=search_id,
            workspace_id=workspace_id,
            query=request.query,
            intent=intent,
            hits=hits,
            confidence=confidence,
            should_clarify=should_clarify,
            resolution_status=resolution_status,
            clarification_reason=clarification_reason,
            missing_slots=missing_slots,
            clarification_question=clarification_question if should_clarify else None,
            top_margin=round(top_margin, 4),
            candidate_count=len(candidates),
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
            trace=(self._build_search_trace(candidates, ranked) if request.debug else None),
        )
        if request.persist_session:
            self._cache_search(response)
            try:
                self.repository.save_search_session(
                    response,
                    filters,
                    ttl_days=self.settings.search_session_ttl_days,
                )
            except Exception:  # noqa: BLE001 - retrieval must survive session storage failures
                pass
        return response

    def explain(self, search_id: str, interface_id: str) -> SearchExplanation | None:
        response = self._get_search(search_id)
        if not response:
            return None
        hit = next((item for item in response.hits if item.interface_id == interface_id), None)
        if not hit:
            return None
        return SearchExplanation(
            search_id=search_id,
            interface_id=interface_id,
            query=response.query,
            intent=response.intent,
            score=hit.score,
            reasons=hit.reasons,
            note=(
                "分类只参与软加权；项目、服务、HTTP 方法、使用端、业务域和动作等"
                "显式条件执行硬过滤。"
            ),
        )

    def record_feedback(self, payload: dict) -> None:
        response = self._get_search(payload["search_id"])
        if response is None:
            raise ValueError("search_not_found")
        self.repository.record_feedback(
            {
                **payload,
                "query": response.query,
                "result_ranking": [hit.interface_id for hit in response.hits],
            }
        )

    def feedback_count(self) -> int:
        return self.repository.feedback_count()

    def _cache_search(self, response: SearchResponse) -> None:
        self._searches[response.search_id] = response
        while len(self._searches) > self.settings.search_session_cache_size:
            self._searches.pop(next(iter(self._searches)))

    def _get_search(self, search_id: str) -> SearchResponse | None:
        cached = self._searches.get(search_id)
        if cached is not None:
            return cached
        try:
            persisted = self.repository.get_search_session(search_id)
        except Exception:  # noqa: BLE001 - compatible with stores awaiting migration
            return None
        if persisted is not None:
            self._cache_search(persisted)
        return persisted

    def _rank(
        self,
        candidates: list[Candidate],
        intent,
        profile: WorkspaceProfile | None = None,
    ) -> list[RankedCandidate]:
        if not candidates:
            return []
        structured_scores = {
            item.endpoint.id: max(
                item.structured_recall_score,
                item.identifier_recall_score,
                item.schema_recall_score,
                item.field_recall_score,
                item.family_recall_score,
                item.service_recall_score,
                item.route_identity_recall_score,
                item.semantic_lexical_score,
            )
            for item in candidates
        }
        lane_specs = (
            ({item.endpoint.id: item.lexical_score for item in candidates}, 0.0),
            ({item.endpoint.id: item.vector_score for item in candidates}, 0.0),
            ({item.endpoint.id: item.semantic_lexical_score for item in candidates}, 0.0),
            (structured_scores, 0.05),
        )
        lane_ranks = []
        for lane, minimum_score in lane_specs:
            supported = {
                interface_id: score for interface_id, score in lane.items() if score > minimum_score
            }
            lane_ranks.append(
                {
                    interface_id: 1 + sum(other_score > score for other_score in supported.values())
                    for interface_id, score in supported.items()
                }
            )
        normalizer = len(lane_specs) / 61
        ranked: list[RankedCandidate] = []
        for candidate in candidates:
            endpoint = candidate.endpoint
            matched_slots, conflicting_slots = _slot_match_details(endpoint, intent, profile)
            supported_lane_count = sum(endpoint.id in lane for lane in lane_ranks)
            rrf_raw = sum(
                1 / (60 + lane[endpoint.id]) for lane in lane_ranks if endpoint.id in lane
            )
            rrf = min(1.0, rrf_raw / normalizer)
            exact = candidate.exact_score
            total = max(0.98, exact) if exact >= 0.95 else min(0.89, 0.89 * rrf)
            query_route_signals = set(infer_query_route_signals(intent.normalized_query))
            endpoint_route_signals = set(
                infer_endpoint_route_signals(
                    project=endpoint.project,
                    service=endpoint.service,
                    path=endpoint.path,
                    operation_id=endpoint.operation_id,
                    title=endpoint.title,
                    actions=endpoint.actions,
                )
            )
            implicit_gateway_bonus = (
                0.015
                if "preference:gateway" in query_route_signals
                and "layer:gateway" in endpoint_route_signals
                else 0.0
            )
            if exact < 0.95:
                total = min(0.89, total + implicit_gateway_bonus)
            if (
                candidate.route_identity_recall_score >= 0.99
                and candidate.service_recall_score >= 0.99
            ):
                total = max(total, 0.95)
            call_layer_conflict = "call_layer" in conflicting_slots and exact < 0.95
            semantic_conflict_penalty = _semantic_conflict_penalty(
                [
                    slot
                    for slot in conflicting_slots
                    if not (
                        slot == "resource"
                        and candidate.route_identity_recall_score >= 0.86
                        and {"transport_mode", "operation_identity"}
                        <= set(matched_slots)
                    )
                    and not (
                        slot in {"resource", "action", "domain"}
                        and candidate.semantic_lexical_score >= 0.55
                    )
                ],
                intent,
                exact=exact,
                authoritative_identity=(
                    candidate.route_identity_recall_score >= 0.99
                    and candidate.service_recall_score >= 0.99
                ),
            )
            conflict_penalty = min(
                0.24,
                (0.18 if call_layer_conflict else 0.0) + semantic_conflict_penalty,
            )
            if conflict_penalty:
                total = max(0.0, total - conflict_penalty)
            if endpoint.semantic_stale:
                total *= 0.9
            structured = structured_scores[endpoint.id]
            features = {
                "exact": exact,
                "lexical": candidate.lexical_score,
                "vector": candidate.vector_score,
                "semantic_lexical": candidate.semantic_lexical_score,
                "structured": structured,
                "rrf": rrf,
                "support_lanes": float(supported_lane_count),
                "call_layer_conflict": float(call_layer_conflict),
                "semantic_conflict_penalty": semantic_conflict_penalty,
                "implicit_gateway_bonus": implicit_gateway_bonus,
            }
            reasons = _base_reasons(candidate)
            if structured > 0:
                reasons.append("命中结构化语义条件")
            if candidate.family_recall_score > 0:
                reasons.append(f"接口家族匹配：{endpoint.interface_family}")
            if candidate.route_identity_recall_score > 0:
                reasons.append("命中服务、入口层级或操作身份")
            if call_layer_conflict:
                reasons.append("调用层级与提示语不一致")
            if semantic_conflict_penalty:
                reasons.append("高置信业务语义条件与提示语不一致")
            if endpoint.semantic_stale:
                reasons.append("接口契约已变化，现有大模型语义待复核")
            ranked.append(
                RankedCandidate(
                    candidate,
                    ScoreBreakdown(
                        exact=round(candidate.exact_score, 4),
                        lexical=round(candidate.lexical_score, 4),
                        vector=round(candidate.vector_score, 4),
                        classification=round(structured, 4),
                        rerank=0,
                        rrf=round(rrf, 4),
                        schema_match=round(
                            max(candidate.schema_recall_score, candidate.field_recall_score),
                            4,
                        ),
                        family_match=round(candidate.family_recall_score, 4),
                        source_confidence=round(endpoint.semantic_confidence, 4),
                        conflict_penalty=round(conflict_penalty, 4),
                        identifier_match=round(candidate.identifier_recall_score, 4),
                        service_match=round(candidate.service_recall_score, 4),
                        route_identity_match=round(
                            candidate.route_identity_recall_score,
                            4,
                        ),
                        features={name: round(value, 4) for name, value in features.items()},
                        total=round(total, 4),
                    ),
                    list(dict.fromkeys(reasons))[:8],
                    matched_slots,
                    conflicting_slots,
                )
            )
        ranked.sort(
            key=lambda item: (
                item.breakdown.total,
                item.breakdown.features.get("implicit_gateway_bonus", 0.0),
                item.candidate.semantic_lexical_score,
                item.candidate.lexical_score,
                item.candidate.endpoint.id,
            ),
            reverse=True,
        )
        return ranked

    @staticmethod
    def _build_search_trace(
        candidates: list[Candidate],
        ranked: list[RankedCandidate],
    ) -> SearchTrace:
        return SearchTrace(
            ranking_strategy_version="support-aware-rrf-v8",
            candidate_pool_ids=[item.endpoint.id for item in candidates],
            candidates=[
                SearchCandidateTrace(
                    interface_id=item.candidate.endpoint.id,
                    retrieval_signals={
                        "exact": round(item.candidate.exact_score, 4),
                        "lexical": round(item.candidate.lexical_score, 4),
                        "vector": round(item.candidate.vector_score, 4),
                        "semantic_lexical": round(
                            item.candidate.semantic_lexical_score,
                            4,
                        ),
                        "schema": round(item.candidate.schema_recall_score, 4),
                        "field": round(item.candidate.field_recall_score, 4),
                        "structured": round(item.candidate.structured_recall_score, 4),
                        "identifier": round(item.candidate.identifier_recall_score, 4),
                        "service": round(item.candidate.service_recall_score, 4),
                        "route_identity": round(
                            item.candidate.route_identity_recall_score,
                            4,
                        ),
                        "family": round(item.candidate.family_recall_score, 4),
                    },
                    ranking_features=item.breakdown.features,
                    total=item.breakdown.total,
                )
                for item in ranked
            ],
        )


def _slot_match_details(
    endpoint: EndpointRecord,
    intent,
    profile: WorkspaceProfile | None = None,
) -> tuple[list[str], list[str]]:
    expected_actions = set(intent.actions) - {"query"} or set(intent.actions)
    normalized_endpoint_actions = normalize_actions(
        endpoint.actions,
        " ".join((endpoint.path, endpoint.operation_id, endpoint.title, endpoint.purpose)),
    )
    actual_actions = set(normalized_endpoint_actions) - {"query"} or set(
        normalized_endpoint_actions
    )
    query_call_layer = infer_query_call_layer(intent.normalized_query)
    endpoint_call_layer = infer_endpoint_call_layer(
        project=endpoint.project,
        service=endpoint.service,
        path=endpoint.path,
        operation_id=endpoint.operation_id,
        title=endpoint.title,
        actions=endpoint.actions,
    )
    query_route_signals = set(infer_query_route_signals(intent.normalized_query))
    endpoint_route_signals = set(
        infer_endpoint_route_signals(
            project=endpoint.project,
            service=endpoint.service,
            path=endpoint.path,
            operation_id=endpoint.operation_id,
            title=endpoint.title,
            actions=endpoint.actions,
            semantic_terms=(
                endpoint.purpose,
                *endpoint.domains,
                *endpoint.scenarios,
                *endpoint.aliases,
            ),
        )
    )
    query_auth = {signal for signal in query_route_signals if signal.startswith("auth:")}
    endpoint_auth = (
        {signal for signal in endpoint_route_signals if signal.startswith("auth:")}
        or {"auth:standard_or_unspecified"}
    )
    route_dimensions = {
        "authentication": (query_auth, endpoint_auth),
        "transport_mode": (
            {signal for signal in query_route_signals if signal.startswith("transport:")},
            {signal for signal in endpoint_route_signals if signal.startswith("transport:")},
        ),
        "operation_identity": (
            {signal for signal in query_route_signals if signal.startswith("operation:")},
            {signal for signal in endpoint_route_signals if signal.startswith("operation:")},
        ),
        "output_form": (
            {signal for signal in query_route_signals if signal.startswith("output:")},
            {signal for signal in endpoint_route_signals if signal.startswith("output:")},
        ),
    }
    actual_resources = {endpoint.resource}
    actual_context_resources: set[str] = set()
    actual_domains = set(endpoint.domains)
    if profile:
        matched_endpoint_resources = _matched_endpoint_resources(endpoint, profile)
        actual_context_resources.update(
            resource
            for resource in matched_endpoint_resources
            if resource != intent.resource
        )
        expected_resources = list(
            dict.fromkeys(
                [intent.resource, *intent.context_resources]
                if intent.resource
                else intent.context_resources
            )
        )
        for expected_resource in expected_resources:
            resource_term = profile.term("resource", expected_resource)
            if not resource_term or expected_resource not in matched_endpoint_resources:
                continue
            if expected_resource == intent.resource:
                actual_resources.add(expected_resource)
            if expected_resource in intent.context_resources:
                actual_context_resources.add(expected_resource)
            actual_domains.update((resource_term.metadata or {}).get("domains", []))
    dimensions = {
        "audience": (set(intent.audiences), set(endpoint.audiences)),
        "service": (set(intent.service_hints), {endpoint.service}),
        "domain": (set(intent.domains), actual_domains),
        "resource": ({intent.resource} if intent.resource else set(), actual_resources),
        "context_resource": (
            set(intent.context_resources),
            actual_context_resources,
        ),
        "action": (expected_actions, actual_actions),
        "lookup_key": (set(intent.lookup_keys), set(endpoint.lookup_keys)),
        "identifier_type": (
            set(intent.identifier_types),
            set(endpoint.lookup_keys),
        ),
        "cardinality": (
            {intent.cardinality} if intent.cardinality != "unknown" else set(),
            {endpoint.cardinality},
        ),
        "ownership": (
            {intent.ownership} if intent.ownership != "unknown" else set(),
            {endpoint.ownership},
        ),
        "call_layer": (
            {query_call_layer} if query_call_layer != "unknown" else set(),
            {endpoint_call_layer} if endpoint_call_layer != "unknown" else set(),
        ),
        **route_dimensions,
    }
    matched = [
        name for name, (expected, actual) in dimensions.items() if expected and expected & actual
    ]
    conflicting = [
        name
        for name, (expected, actual) in dimensions.items()
        if expected and actual and "unknown" not in actual and not expected & actual
    ]
    actual_by_dimension = {
        "audience": set(endpoint.audiences),
        "service": {endpoint.service},
        "domain": set(endpoint.domains),
        "resource": {endpoint.resource},
        "action": actual_actions,
        "lookup_key": set(endpoint.lookup_keys),
        "cardinality": {endpoint.cardinality},
        "ownership": {endpoint.ownership},
    }
    conflicting.extend(
        f"negative_{name}"
        for name, excluded in intent.negative_slots.items()
        if set(excluded) & actual_by_dimension.get(name, set())
    )
    return matched, conflicting


def _matched_endpoint_resources(
    endpoint: EndpointRecord,
    profile: WorkspaceProfile,
) -> set[str]:
    """Match configured resources against semantic text and technical identity.

    Workspace vocabulary remains data.  The engine only supplies a generic,
    boundary-aware matcher so a context resource such as a parent aggregate is
    not collapsed into a longer adjacent resource name.  Explicit semantic
    wording wins; technical matches use longest-token-set precedence.
    """

    semantic_text = " ".join(
        (
            endpoint.title,
            endpoint.purpose,
            *endpoint.entities,
            *endpoint.aliases,
            *endpoint.discriminators,
        )
    ).casefold()
    technical_tokens = set(
        _technical_identity_tokens(
            " ".join(
                (
                    endpoint.path,
                    endpoint.operation_id,
                    endpoint.controller_name,
                    endpoint.interface_family,
                )
            )
        )
    )
    semantic_matches: set[str] = set()
    technical_matches: dict[str, set[str]] = {}
    for resource_term in profile.terms:
        if not resource_term.active or resource_term.dimension != "resource":
            continue
        for alias in dict.fromkeys(
            [resource_term.canonical_value, *resource_term.aliases]
        ):
            normalized = alias.strip().casefold()
            if not normalized:
                continue
            if re.search(r"[\u4e00-\u9fff]", normalized):
                if normalized in semantic_text:
                    semantic_matches.add(resource_term.canonical_value)
                continue
            alias_tokens = set(_technical_identity_tokens(normalized))
            if alias_tokens and alias_tokens <= technical_tokens:
                previous = technical_matches.get(resource_term.canonical_value, set())
                if len(alias_tokens) > len(previous):
                    technical_matches[resource_term.canonical_value] = alias_tokens

    retained_technical = {
        canonical
        for canonical, tokens in technical_matches.items()
        if not any(
            tokens < other_tokens
            for other_canonical, other_tokens in technical_matches.items()
            if other_canonical != canonical
        )
    }
    return semantic_matches | retained_technical


def _technical_identity_tokens(value: str) -> list[str]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    return [
        token
        for token in re.split(r"[^a-z0-9]+", expanded.casefold())
        if token
    ]


def _semantic_conflict_penalty(
    conflicting_slots: list[str],
    intent,
    *,
    exact: float,
    authoritative_identity: bool = False,
) -> float:
    """Apply a bounded soft penalty only to explicit, high-confidence slot conflicts."""

    if exact >= 0.95 or authoritative_identity:
        return 0.0
    weights = {
        "domain": 0.05,
        "resource": 0.06,
        "context_resource": 0.06,
        "action": 0.05,
        "lookup_key": 0.04,
        "identifier_type": 0.04,
        "cardinality": 0.03,
    }
    penalty = min(
        0.12,
        sum(
            weight
            for slot, weight in weights.items()
            if slot in conflicting_slots and intent.slot_confidences.get(slot, 0.0) >= 0.82
        ),
    )
    explicit_route_weights = {
        "authentication": 0.08,
        "transport_mode": 0.07,
        "operation_identity": 0.06,
        "output_form": 0.05,
    }
    penalty += sum(
        weight for slot, weight in explicit_route_weights.items() if slot in conflicting_slots
    )
    return round(min(0.18, penalty), 4)


_GENERIC_QUERY_TERMS = {
    "查询",
    "分页",
    "列表",
    "详情",
    "运营",
    "营端",
    "门户",
    "户端",
    "前端",
    "客户端",
    "按id",
    "id",
    "接口",
    "信息",
    "数据",
    "query",
    "page",
    "list",
    "detail",
    "get",
    "post",
}


def _distinctive_query_terms(text: str) -> list[str]:
    """Extract workspace-neutral business tokens for focused lexical recall."""

    masked = re.sub(
        r"(?:系统管理端|运营管理端|运营后台|运营端|管理端|后台|"
        r"PC客户门户|客户端|前端|门户端|门户|登录用户|当前用户|"
        r"按(?:主键|编号|编码|ID|id)|根据(?:主键|编号|编码|ID|id)|"
        r"分页查询|查询分页|查询|查看|获取|分页|列表|详情|信息|数据)",
        " ",
        text,
        flags=re.I,
    )
    return list(
        dict.fromkeys(
            token
            for token in tokenize(masked)
            if len(token) >= 2 and token not in _GENERIC_QUERY_TERMS
        )
    )[:30]


def _base_reasons(candidate: Candidate) -> list[str]:
    reasons = []
    if candidate.exact_score >= 0.8:
        reasons.append("精确命中接口路径、操作标识或业务别名")
    if candidate.lexical_score >= 0.25:
        reasons.append("关键词与接口语义文本高度重合")
    if candidate.vector_score >= 0.45:
        reasons.append("向量语义相似")
    return reasons
