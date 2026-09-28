#!/usr/bin/env python3
"""Rebuild derived interface-search documents without changing reviewed semantics."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from typing import Any

from context_router.interface_search.config import Settings
from context_router.interface_search.embedding import create_embedding_provider
from context_router.interface_search.repository import PostgresEndpointRepository
from context_router.interface_search.search import build_lexical_document, build_search_document

_DERIVED_FIELDS = {
    "search_document",
    "search_document_zh",
    "embedding",
    "search_document_version",
    "embedding_version",
    "last_seen_at",
    "updated_at",
}


def _stable_payload(endpoint: Any) -> dict[str, Any]:
    return endpoint.model_dump(mode="json", exclude=_DERIVED_FIELDS)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild derived interface search documents and embeddings"
    )
    parser.add_argument("--workspace", default="", help="Optional workspace id")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    if arguments.batch_size < 1 or arguments.batch_size > 1000:
        raise ValueError("batch-size must be between 1 and 1000")

    database_url = os.environ.get("CONTEXT_ROUTER_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("CONTEXT_ROUTER_DATABASE_URL is required")
    settings = Settings(database_url=database_url)
    repository = PostgresEndpointRepository(database_url)
    provider = create_embedding_provider(
        provider=settings.embedding_provider,
        dimensions=settings.embedding_dimensions,
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        api_key=settings.embedding_api_key,
    )
    total, endpoints = repository.list_interfaces(
        workspace_id=arguments.workspace,
        query="",
        service=None,
        method=None,
        semantic_status="all",
        offset=0,
        limit=1_000_000,
    )
    if total != len(endpoints):
        raise RuntimeError(f"incomplete interface listing: total={total}, loaded={len(endpoints)}")

    before_versions = Counter(endpoint.search_document_version for endpoint in endpoints)
    planned = sum(
        endpoint.search_document_version != "v4"
        or "路由身份:" not in endpoint.search_document
        for endpoint in endpoints
    )
    if not arguments.apply:
        print(
            json.dumps(
                {
                    "workspace_id": arguments.workspace or None,
                    "active_interfaces": total,
                    "current_versions": before_versions,
                    "planned_updates": planned,
                    "applied": 0,
                },
                ensure_ascii=False,
                default=dict,
            )
        )
        return 0

    profiles: dict[str, Any] = {}
    applied = 0
    for start in range(0, len(endpoints), arguments.batch_size):
        batch = endpoints[start : start + arguments.batch_size]
        documents: list[str] = []
        for endpoint in batch:
            document = build_search_document(endpoint)
            if endpoint.workspace_id not in profiles:
                profiles[endpoint.workspace_id] = repository.get_workspace_profile(
                    endpoint.workspace_id
                )
            if profile := profiles[endpoint.workspace_id]:
                document = profile.expand_text(document, dimensions=("endpoint_alias",))
            documents.append(document)
        vectors = provider.embed(documents)
        prepared = [
            endpoint.model_copy(
                update={
                    "search_document": document,
                    "search_document_zh": build_lexical_document(document),
                    "embedding": vector,
                    "search_document_version": "v4",
                }
            )
            for endpoint, document, vector in zip(batch, documents, vectors, strict=True)
        ]
        saved = repository.add_many(prepared)
        if len(saved) != len(batch):
            raise RuntimeError(f"incomplete batch update at offset {start}")
        for previous, current in zip(batch, saved, strict=True):
            if _stable_payload(previous) != _stable_payload(current):
                raise RuntimeError(f"non-derived interface fields changed: {previous.id}")
        applied += len(saved)
        print(f"progress={applied}/{total}", flush=True)

    _, verified = repository.list_interfaces(
        workspace_id=arguments.workspace,
        query="",
        service=None,
        method=None,
        semantic_status="all",
        offset=0,
        limit=1_000_000,
    )
    version_counts = Counter(endpoint.search_document_version for endpoint in verified)
    route_document_count = sum("路由身份:" in endpoint.search_document for endpoint in verified)
    if version_counts != {"v4": total} or route_document_count != total:
        raise RuntimeError(
            f"verification failed: versions={dict(version_counts)}, "
            f"route_documents={route_document_count}/{total}"
        )
    print(
        json.dumps(
            {
                "workspace_id": arguments.workspace or None,
                "active_interfaces": total,
                "previous_versions": before_versions,
                "applied": applied,
                "verified_versions": version_counts,
                "route_documents": route_document_count,
            },
            ensure_ascii=False,
            default=dict,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
