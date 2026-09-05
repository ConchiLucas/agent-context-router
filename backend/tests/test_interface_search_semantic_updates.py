from __future__ import annotations

from context_router.interface_search.config import Settings
from context_router.interface_search.domain import (
    BusinessIdentifier,
    EndpointRecord,
    EndpointSemanticUpdate,
    RequiredInput,
)
from context_router.interface_search.embedding import LocalFeatureEmbedding
from context_router.interface_search.repository import InMemoryEndpointRepository
from context_router.interface_search.search import SearchService


def _service_with_existing_semantics() -> tuple[SearchService, str]:
    repository = InMemoryEndpointRepository()
    endpoint = EndpointRecord(
        id="endpoint-1",
        workspace_id="workspace-1",
        project="project-1",
        service="service-1",
        method="POST",
        path="/api/things/detail",
        title="查询对象详情",
        purpose="旧用途",
        actions=["detail"],
        resource="thing",
        lookup_keys=["id"],
        cardinality="one",
        ownership="self",
        discriminators=["旧区别"],
        required_inputs=[
            RequiredInput(name="id", location="body", required=True, schema_type="Long")
        ],
        business_identifiers=[
            BusinessIdentifier(
                canonical="thing_id",
                technical_names=["id"],
                resource="thing",
            )
        ],
    )
    repository.add_many([endpoint])
    service = SearchService(
        repository,
        LocalFeatureEmbedding(128),
        Settings(embedding_dimensions=128),
    )
    return service, endpoint.id


def _minimum_update(**values: object) -> EndpointSemanticUpdate:
    return EndpointSemanticUpdate.model_validate(
        {
            "purpose": "新用途",
            "semantic_model": "source-review",
            "semantic_confidence": 0.97,
            "semantic_evidence": ["Controller#method -> Service#method"],
            **values,
        }
    )


def test_explicit_empty_and_unknown_semantics_replace_inferred_values() -> None:
    service, endpoint_id = _service_with_existing_semantics()

    saved = service.update_semantics(
        endpoint_id,
        _minimum_update(
            actions=[],
            resource="",
            lookup_keys=[],
            cardinality="unknown",
            ownership="unknown",
            discriminators=[],
            required_inputs=[],
            business_identifiers=[],
        ),
    )

    assert saved is not None
    assert saved.actions == []
    assert saved.resource == ""
    assert saved.lookup_keys == []
    assert saved.cardinality == "unknown"
    assert saved.ownership == "unknown"
    assert saved.discriminators == []
    assert saved.required_inputs == []
    assert saved.business_identifiers == []


def test_omitted_optional_semantics_keep_existing_values() -> None:
    service, endpoint_id = _service_with_existing_semantics()

    saved = service.update_semantics(endpoint_id, _minimum_update())

    assert saved is not None
    assert saved.resource == "thing"
    assert saved.lookup_keys == ["id", "thing_id"]
    assert saved.cardinality == "one"
    assert saved.ownership == "self"
    assert saved.discriminators == ["旧区别"]
    assert [item.name for item in saved.required_inputs] == ["id"]
    assert [item.canonical for item in saved.business_identifiers] == ["thing_id"]
