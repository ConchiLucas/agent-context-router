from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class RequiredInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    zh_name: str = Field(default="", max_length=160)
    location: Literal["path", "query", "header", "body", "unknown"] = "unknown"
    required: bool = False
    schema_type: str = Field(default="", max_length=120)


class SchemaFieldPath(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    normalized_name: str = Field(default="", max_length=240)
    meaning: str = Field(default="", max_length=500)
    data_type: str = Field(default="", max_length=120)
    required: bool = False
    location: Literal["path", "query", "header", "body", "response", "unknown"] = "unknown"
    source: str = Field(default="contract", max_length=80)
    confidence: float = Field(default=0.95, ge=0, le=1)


class BusinessIdentifier(BaseModel):
    canonical: str = Field(min_length=1, max_length=240)
    display_name: str = Field(default="", max_length=240)
    technical_names: list[str] = Field(default_factory=list, max_length=20)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    resource: str = Field(default="", max_length=160)
    source: str = Field(default="contract", max_length=80)
    confidence: float = Field(default=0.9, ge=0, le=1)


class EndpointCreate(BaseModel):
    workspace_id: str = Field(default="", max_length=120)
    project: str = Field(min_length=1, max_length=120)
    service: str = Field(min_length=1, max_length=120)
    method: str = Field(pattern=r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$")
    path: str = Field(min_length=1, max_length=600)
    operation_id: str = Field(default="", max_length=240)
    title: str = Field(min_length=1, max_length=300)
    purpose: str = Field(min_length=1, max_length=4000)
    audiences: list[str] = Field(default_factory=list, max_length=20)
    domains: list[str] = Field(default_factory=list, max_length=30)
    scenarios: list[str] = Field(default_factory=list, max_length=30)
    actions: list[str] = Field(default_factory=list, max_length=20)
    entities: list[str] = Field(default_factory=list, max_length=50)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    resource: str = Field(default="", max_length=160)
    lookup_keys: list[str] = Field(default_factory=list, max_length=30)
    cardinality: Literal["unknown", "one", "many"] = "unknown"
    ownership: Literal["unknown", "self", "all", "by_id"] = "unknown"
    discriminators: list[str] = Field(default_factory=list, max_length=30)
    required_inputs: list[RequiredInput] = Field(default_factory=list, max_length=50)
    request_schema_paths: list[SchemaFieldPath] = Field(default_factory=list, max_length=120)
    response_schema_paths: list[SchemaFieldPath] = Field(default_factory=list, max_length=120)
    business_identifiers: list[BusinessIdentifier] = Field(default_factory=list, max_length=50)
    semantic_field_sources: dict[str, str] = Field(default_factory=dict)
    semantic_confidences: dict[str, float] = Field(default_factory=dict)
    search_document_version: str = Field(default="v3", max_length=40)
    embedding_version: str = Field(default="local-feature-v1", max_length=80)
    controller_name: str = Field(default="", max_length=240)
    interface_family: str = Field(default="", max_length=240)
    sibling_actions: dict[str, list[str]] = Field(default_factory=dict)
    distinguishing_features: dict[str, str] = Field(default_factory=dict)
    family_size: int = Field(default=1, ge=1)
    tags: list[str] = Field(default_factory=list, max_length=50)
    request_schema: dict[str, Any] = Field(default_factory=dict)
    response_schema: dict[str, Any] = Field(default_factory=dict)
    source_locations: list[str] = Field(default_factory=list, max_length=30)
    semantic_source: str = Field(default="manual", max_length=60)
    semantic_model: str = Field(default="", max_length=160)
    semantic_confidence: float = Field(default=0.5, ge=0, le=1)
    semantic_evidence: list[str] = Field(default_factory=list, max_length=50)


class EndpointRecord(EndpointCreate):
    id: str = Field(default_factory=lambda: str(uuid4()))
    search_document: str = ""
    search_document_zh: str = ""
    embedding: list[float] | None = None
    contract_hash: str = ""
    contract_hash_version: str = "v1"
    semantic_stale: bool = False
    active: bool = True
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InterfaceListItem(BaseModel):
    id: str
    workspace_id: str
    project: str
    service: str
    method: str
    path: str
    operation_id: str
    title: str
    purpose: str
    audiences: list[str]
    domains: list[str]
    scenarios: list[str]
    resource: str
    controller_name: str
    interface_family: str
    family_size: int
    cardinality: Literal["unknown", "one", "many"]
    semantic_source: str
    semantic_model: str
    semantic_confidence: float
    semantic_stale: bool
    updated_at: datetime


class InterfaceListResponse(BaseModel):
    items: list[InterfaceListItem]
    total: int
    offset: int
    limit: int


class SearchFilters(BaseModel):
    projects: list[str] = Field(default_factory=list, max_length=20)
    services: list[str] = Field(default_factory=list, max_length=30)
    methods: list[str] = Field(default_factory=list, max_length=10)
    audiences: list[str] = Field(default_factory=list, max_length=20)
    domains: list[str] = Field(default_factory=list, max_length=30)
    actions: list[str] = Field(default_factory=list, max_length=20)
    resources: list[str] = Field(default_factory=list, max_length=20)
    lookup_keys: list[str] = Field(default_factory=list, max_length=30)
    cardinalities: list[Literal["unknown", "one", "many"]] = Field(
        default_factory=list, max_length=3
    )


class SearchRequest(BaseModel):
    workspace_id: str = Field(default="", max_length=120)
    query: str = Field(min_length=1, max_length=2000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = Field(default=15, ge=1, le=20)
    persist_session: bool = True
    debug: bool = False


class IntentCandidate(BaseModel):
    value: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


class NegativeConstraint(BaseModel):
    slot: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=240)
    scope: str = Field(default="", max_length=500)
    marker: str = Field(default="", max_length=20)
    confidence: float = Field(default=0.8, ge=0, le=1)


class QueryIntent(BaseModel):
    raw_query: str = ""
    normalized_query: str
    positive_query: str = ""
    audiences: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    qualifiers: list[str] = Field(default_factory=list)
    explicit_method: str | None = None
    exact_identifiers: list[str] = Field(default_factory=list)
    endpoint_identifiers: list[str] = Field(default_factory=list)
    field_identifiers: list[str] = Field(default_factory=list)
    field_paths: list[str] = Field(default_factory=list)
    schema_direction: Literal["unknown", "request", "response"] = "unknown"
    resource: str = ""
    target_resource: str = ""
    context_resources: list[str] = Field(default_factory=list)
    resource_candidates: list[IntentCandidate] = Field(default_factory=list)
    service_hints: list[str] = Field(default_factory=list)
    explicit_audiences: list[str] = Field(default_factory=list)
    lookup_keys: list[str] = Field(default_factory=list)
    identifier_types: list[str] = Field(default_factory=list)
    cardinality: Literal["unknown", "one", "many"] = "unknown"
    ownership: Literal["unknown", "self", "all", "by_id"] = "unknown"
    positive_slots: dict[str, list[str]] = Field(default_factory=dict)
    negative_slots: dict[str, list[str]] = Field(default_factory=dict)
    negative_constraints: list[NegativeConstraint] = Field(default_factory=list)
    slot_confidences: dict[str, float] = Field(default_factory=dict)
    uncertain_slots: list[str] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    exact: float
    lexical: float
    vector: float
    classification: float
    rerank: float
    rrf: float
    schema_match: float = 0
    family_match: float = 0
    source_confidence: float = 0
    conflict_penalty: float = 0
    negative_penalty: float = 0
    identifier_match: float = 0
    service_match: float = 0
    features: dict[str, float] = Field(default_factory=dict)
    total: float


class SearchCandidateTrace(BaseModel):
    interface_id: str
    retrieval_signals: dict[str, float] = Field(default_factory=dict)
    ranking_features: dict[str, float] = Field(default_factory=dict)
    total: float = 0


class SearchTrace(BaseModel):
    query_understanding_version: str = "query-v7"
    ranking_strategy_version: str = "support-aware-rrf-v2"
    candidate_pool_ids: list[str] = Field(default_factory=list)
    candidates: list[SearchCandidateTrace] = Field(default_factory=list)


class SearchHit(BaseModel):
    rank: int
    retrieval_rank: int
    interface_id: str
    workspace_id: str
    project: str
    service: str
    method: str
    path: str
    operation_id: str
    primary_source_location: str | None = None
    title: str
    purpose: str
    audiences: list[str]
    domains: list[str]
    scenarios: list[str]
    resource: str = ""
    actions: list[str] = Field(default_factory=list)
    lookup_keys: list[str] = Field(default_factory=list)
    cardinality: Literal["unknown", "one", "many"] = "unknown"
    discriminators: list[str] = Field(default_factory=list)
    matched_slots: list[str] = Field(default_factory=list)
    conflicting_slots: list[str] = Field(default_factory=list)
    controller_name: str = ""
    interface_family: str = ""
    family_size: int = 1
    sibling_actions: dict[str, list[str]] = Field(default_factory=dict)
    semantic_stale: bool = False
    confidence: float
    score: ScoreBreakdown
    reasons: list[str]


class InterfaceResolveRequest(BaseModel):
    workspace_id: str = Field(default="", max_length=120)
    query: str = Field(min_length=1, max_length=2000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    candidate_limit: int = Field(default=5, ge=2, le=5)
    persist_session: bool = True


class InterfaceResolutionOption(BaseModel):
    interface_id: str
    method: str
    path: str
    title: str
    purpose: str
    audiences: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    resource: str = ""
    actions: list[str] = Field(default_factory=list)
    lookup_keys: list[str] = Field(default_factory=list)
    discriminators: list[str] = Field(default_factory=list)
    matched_evidence: list[str] = Field(default_factory=list)


class InterfaceResolutionResponse(BaseModel):
    search_id: str
    workspace_id: str = ""
    query: str
    status: Literal["resolved", "needs_selection", "no_candidate"]
    selected_interface_id: str | None = None
    recommended_interface_id: str | None = None
    reason: str = ""
    question: str | None = None
    options: list[InterfaceResolutionOption] = Field(default_factory=list)
    elapsed_ms: float = 0


class InterfaceCompareRequest(BaseModel):
    interface_ids: list[str] = Field(min_length=2, max_length=5)


class InterfaceComparisonItem(BaseModel):
    interface_id: str
    method: str
    path: str
    operation_id: str
    title: str
    purpose: str
    audiences: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)
    resource: str = ""
    actions: list[str] = Field(default_factory=list)
    lookup_keys: list[str] = Field(default_factory=list)
    cardinality: Literal["unknown", "one", "many"] = "unknown"
    ownership: Literal["unknown", "self", "all", "by_id"] = "unknown"
    discriminators: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)
    business_identifiers: list[str] = Field(default_factory=list)
    distinguishing_features: dict[str, str] = Field(default_factory=dict)
    differences: dict[str, list[str]] = Field(default_factory=dict)


class InterfaceCompareResponse(BaseModel):
    workspace_id: str
    common: dict[str, list[str]] = Field(default_factory=dict)
    differing_dimensions: list[str] = Field(default_factory=list)
    decision_rule: str = ""
    items: list[InterfaceComparisonItem]


class SearchResponse(BaseModel):
    search_id: str
    workspace_id: str = ""
    query: str
    intent: QueryIntent
    hits: list[SearchHit]
    confidence: Literal["high", "medium", "low"]
    should_clarify: bool
    resolution_status: Literal["resolved", "ambiguous", "no_reliable_candidate", "no_candidate"] = (
        "resolved"
    )
    clarification_reason: str = ""
    missing_slots: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    top_margin: float = 0
    candidate_count: int = 0
    elapsed_ms: float = 0
    trace: SearchTrace | None = None


class SearchExplanation(BaseModel):
    search_id: str
    interface_id: str
    query: str
    intent: QueryIntent
    score: ScoreBreakdown
    reasons: list[str]
    note: str


class FeedbackCreate(BaseModel):
    search_id: str
    selected_interface_id: str | None = None
    expected_interface_id: str | None = None
    relevant: bool | None = None
    note: str = Field(default="", max_length=1000)


class EndpointSemanticUpdate(BaseModel):
    purpose: str = Field(min_length=1, max_length=4000)
    audiences: list[str] = Field(default_factory=list, max_length=20)
    domains: list[str] = Field(default_factory=list, max_length=30)
    scenarios: list[str] = Field(default_factory=list, max_length=30)
    actions: list[str] = Field(default_factory=list, max_length=20)
    entities: list[str] = Field(default_factory=list, max_length=50)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    resource: str = Field(default="", max_length=160)
    lookup_keys: list[str] = Field(default_factory=list, max_length=30)
    cardinality: Literal["unknown", "one", "many"] = "unknown"
    ownership: Literal["unknown", "self", "all", "by_id"] = "unknown"
    discriminators: list[str] = Field(default_factory=list, max_length=30)
    required_inputs: list[RequiredInput] = Field(default_factory=list, max_length=50)
    business_identifiers: list[BusinessIdentifier] = Field(default_factory=list, max_length=50)
    semantic_model: str = Field(min_length=1, max_length=160)
    semantic_confidence: float = Field(ge=0, le=1)
    semantic_evidence: list[str] = Field(min_length=1, max_length=50)


class EndpointSemanticBatchItem(EndpointSemanticUpdate):
    interface_id: str = Field(min_length=1)


class EndpointSemanticBatchUpdate(BaseModel):
    items: list[EndpointSemanticBatchItem] = Field(min_length=1, max_length=100)


class ImportOpenAPIRequest(BaseModel):
    project: str = Field(min_length=1, max_length=120)
    service: str = Field(min_length=1, max_length=120)
    document: dict[str, Any]


class EvaluationCase(BaseModel):
    case_id: str = ""
    query: str
    expected_interface_ids: list[str] = Field(min_length=1)
    split: Literal["development", "regression", "blind"] = "development"
    category: str = "semantic"
    expected_should_clarify: bool | None = None
    source_evidence: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class EvaluationRequest(BaseModel):
    cases: list[EvaluationCase] = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    suite: str = "ad_hoc"
    split: Literal["development", "regression", "blind"] | None = None
    include_case_results: bool = False


class EvaluationResult(BaseModel):
    suite: str = "ad_hoc"
    split: str = ""
    case_count: int
    ranking_case_count: int = 0
    ambiguity_case_count: int = 0
    clarification_labeled_case_count: int = 0
    top1_accuracy: float
    recall_at_k: float
    candidate_pool_recall: float = 0
    mrr: float
    exact_identifier_accuracy: float | None = None
    schema_field_recall_at_5: float | None = None
    ambiguity_detection_accuracy: float | None = None
    wrong_confident_rate: float = 0
    high_confidence_error_count: int = 0
    category_metrics: dict[str, dict[str, float | int]] = Field(default_factory=dict)
    failures: list[dict[str, Any]]
    case_results: list[dict[str, Any]] = Field(default_factory=list)
