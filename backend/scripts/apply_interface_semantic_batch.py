#!/usr/bin/env python3
"""Validate and apply an interface semantic batch without business logic in code."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from context_router.interface_search.config import Settings
from context_router.interface_search.domain import EndpointSemanticUpdate
from context_router.interface_search.embedding import LocalFeatureEmbedding
from context_router.interface_search.repository import PostgresEndpointRepository
from context_router.interface_search.search import SearchService

_SEMANTIC_FIELDS = (
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
    "required_inputs",
    "business_identifiers",
    "semantic_model",
    "semantic_confidence",
    "semantic_evidence",
)


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _payload(item: dict[str, Any], source: Any | None) -> EndpointSemanticUpdate:
    values: dict[str, Any] = {}
    if source is not None:
        source_values = source.model_dump()
        values.update({field: source_values[field] for field in _SEMANTIC_FIELDS})
    values.update(item.get("semantic") or {})
    if prefix := str(item.get("purpose_prefix") or "").strip():
        values["purpose"] = f"{prefix}{values.get('purpose', '')}"
    for field in ("audiences", "domains", "scenarios", "actions", "entities", "aliases",
                  "lookup_keys", "discriminators", "semantic_evidence"):
        additions = _list(item.get(f"{field}_add"))
        if additions:
            values[field] = list(dict.fromkeys([*_list(values.get(field)), *additions]))
    return EndpointSemanticUpdate.model_validate(values)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a validated interface semantic batch")
    parser.add_argument("batch", type=Path)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    database_url = os.environ.get("CONTEXT_ROUTER_DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("CONTEXT_ROUTER_DATABASE_URL is required")

    document = json.loads(arguments.batch.read_text(encoding="utf-8"))
    items = document.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("batch.items must be a non-empty array")
    repository = PostgresEndpointRepository(database_url)
    service = SearchService(
        repository,
        LocalFeatureEmbedding(1024),
        Settings(database_url=database_url),
    )
    prepared: list[tuple[str, EndpointSemanticUpdate]] = []
    seen: set[str] = set()
    for item in items:
        interface_id = str(item.get("interface_id") or "")
        if not interface_id or interface_id in seen:
            raise ValueError(f"empty or duplicate interface_id: {interface_id!r}")
        seen.add(interface_id)
        endpoint = repository.get(interface_id)
        if endpoint is None:
            raise ValueError(f"interface not found: {interface_id}")
        expected = item.get("expected_identity") or {}
        actual_identity = {
            "service": endpoint.service,
            "method": endpoint.method,
            "path": endpoint.path,
        }
        for key, expected_value in expected.items():
            if actual_identity.get(key) != expected_value:
                raise ValueError(
                    f"{interface_id}: {key} changed; expected={expected_value!r}, "
                    f"actual={actual_identity.get(key)!r}"
                )
        source = None
        if source_id := str(item.get("copy_from_interface_id") or ""):
            source = repository.get(source_id)
            if source is None or source.semantic_source != "llm_source_analysis":
                raise ValueError(f"invalid reviewed semantic source: {source_id}")
        prepared.append((interface_id, _payload(item, source)))

    if arguments.apply:
        for interface_id, payload in prepared:
            if service.update_semantics(interface_id, payload, rebuild_families=False) is None:
                raise RuntimeError(f"failed to update: {interface_id}")
        repository.rebuild_interface_families()
    print(
        json.dumps(
            {
                "batch": document.get("batch_id"),
                "validated": len(prepared),
                "applied": len(prepared) if arguments.apply else 0,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
