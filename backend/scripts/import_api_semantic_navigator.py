from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from context_router.interface_search.domain import EndpointRecord
from context_router.interface_search.repository import (
    PostgresEndpointRepository,
    _row_to_endpoint,
)
from context_router.interface_search.workspaces import WorkspaceProfile, WorkspaceTerm

_PATH_PARAMETER = re.compile(r"\{[^{}]+\}")


def _canonical_path(path: str) -> str:
    return _PATH_PARAMETER.sub("{}", path.rstrip("/") or "/")


@dataclass(frozen=True)
class TargetInterface:
    interface_id: str
    workspace_id: str
    project: str
    service: str
    method: str
    path: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.service.casefold(), self.method.upper(), self.path)

    @property
    def method_path_key(self) -> tuple[str, str]:
        return (self.method.upper(), self.path)

    @property
    def canonical_method_path_key(self) -> tuple[str, str]:
        return (self.method.upper(), _canonical_path(self.path))


def _replace_database(database_url: str, database: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(
        SplitResult(parsed.scheme, parsed.netloc, f"/{database}", parsed.query, parsed.fragment)
    )


def _source_scope(database_url: str, workspace_id: str | None) -> str:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            "SELECT workspace_id, count(*) FROM api_endpoints "
            "WHERE active GROUP BY workspace_id ORDER BY workspace_id"
        ).fetchall()
    available = {str(row[0]): int(row[1]) for row in rows}
    if workspace_id:
        if workspace_id not in available:
            raise RuntimeError(f"Source workspace not found: {workspace_id}")
        return workspace_id
    if len(available) != 1:
        raise RuntimeError(
            "Source database has multiple workspaces; pass --source-workspace explicitly"
        )
    return next(iter(available))


def _target_scope(database_url: str, workspace_id: str | None) -> tuple[str, str]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT workspace.id, workspace.name, count(interface.id)
            FROM workspaces AS workspace
            JOIN interface_forwarding_interfaces AS interface
              ON interface.workspace_id=workspace.id
            GROUP BY workspace.id, workspace.name
            ORDER BY workspace.name
            """
        ).fetchall()
    available = {str(row[0]): (str(row[1]), int(row[2])) for row in rows}
    if workspace_id:
        if workspace_id not in available:
            raise RuntimeError(f"Target workspace not found or has no interfaces: {workspace_id}")
        return workspace_id, available[workspace_id][0]
    if len(available) != 1:
        raise RuntimeError(
            "Target database has multiple interface workspaces; pass --target-workspace explicitly"
        )
    selected = next(iter(available))
    return selected, available[selected][0]


def _source_endpoints(database_url: str, workspace_id: str) -> list[EndpointRecord]:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        register_vector(connection)
        rows = connection.execute(
            "SELECT * FROM api_endpoints WHERE active AND workspace_id=%s ORDER BY id",
            (workspace_id,),
        ).fetchall()
    return [_row_to_endpoint(dict(row)) for row in rows]


def _target_interfaces(database_url: str, workspace_id: str) -> list[TargetInterface]:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT interface.id AS interface_id, interface.workspace_id,
                   semantic.project, service.name AS service,
                   interface.method, interface.path
            FROM interface_forwarding_interfaces AS interface
            JOIN interface_forwarding_services AS service ON service.id=interface.service_id
            JOIN interface_semantic_index AS semantic ON semantic.id=interface.id
            WHERE interface.workspace_id=%s
            ORDER BY service.name, interface.path, interface.method
            """,
            (workspace_id,),
        ).fetchall()
    return [TargetInterface(**dict(row)) for row in rows]


def _source_profile(database_url: str, workspace_id: str) -> WorkspaceProfile | None:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        workspace = connection.execute(
            "SELECT * FROM api_workspaces WHERE id=%s AND active",
            (workspace_id,),
        ).fetchone()
        if workspace is None:
            return None
        terms = connection.execute(
            "SELECT * FROM api_workspace_terms "
            "WHERE workspace_id=%s AND active ORDER BY priority DESC, id",
            (workspace_id,),
        ).fetchall()
    return WorkspaceProfile(
        workspace_id=str(workspace["id"]),
        name=str(workspace["name"]),
        source_root=str(workspace["source_root"] or ""),
        semantic_profile_version=str(workspace["semantic_profile_version"]),
        metadata=dict(workspace["metadata"] or {}),
        terms=[
            WorkspaceTerm(
                dimension=str(row["dimension"]),
                canonical_value=str(row["canonical_value"]),
                aliases=list(row["aliases"] or []),
                mapped_values=dict(row["mapped_values"] or {}),
                metadata=dict(row["metadata"] or {}),
                priority=int(row["priority"]),
                source=str(row["source"]),
                confidence=float(row["confidence"]),
                active=bool(row["active"]),
            )
            for row in terms
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Import a standalone api-semantic-navigator index into the host interface index "
            "using only exact service, method, and path identity matches."
        )
    )
    parser.add_argument("--source-database-url")
    parser.add_argument("--source-database", default="api_semantic_navigator")
    parser.add_argument("--source-workspace")
    parser.add_argument("--target-workspace")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the exact matches. Without this flag the command is read-only.",
    )
    args = parser.parse_args()

    target_url = os.environ.get("CONTEXT_ROUTER_DATABASE_URL", "")
    if not target_url:
        raise RuntimeError("CONTEXT_ROUTER_DATABASE_URL is required")
    source_url = args.source_database_url or _replace_database(target_url, args.source_database)
    source_workspace = _source_scope(source_url, args.source_workspace)
    target_workspace, target_workspace_name = _target_scope(
        target_url, args.target_workspace
    )

    source_endpoints = _source_endpoints(source_url, source_workspace)
    target_endpoints = _target_interfaces(target_url, target_workspace)
    targets_by_key: dict[tuple[str, str, str], list[TargetInterface]] = {}
    targets_by_method_path: dict[tuple[str, str], list[TargetInterface]] = {}
    targets_by_canonical_method_path: dict[tuple[str, str], list[TargetInterface]] = {}
    for endpoint in target_endpoints:
        targets_by_key.setdefault(endpoint.key, []).append(endpoint)
        targets_by_method_path.setdefault(endpoint.method_path_key, []).append(endpoint)
        targets_by_canonical_method_path.setdefault(
            endpoint.canonical_method_path_key, []
        ).append(endpoint)

    matched: list[EndpointRecord] = []
    matched_by_service = 0
    matched_by_unique_method_path = 0
    matched_by_canonical_path = 0
    unmatched: list[EndpointRecord] = []
    ambiguous: list[EndpointRecord] = []
    for endpoint in source_endpoints:
        candidates = targets_by_key.get(
            (endpoint.service.casefold(), endpoint.method.upper(), endpoint.path), []
        )
        matched_exact_service = bool(candidates)
        if not candidates:
            candidates = targets_by_method_path.get((endpoint.method.upper(), endpoint.path), [])
        matched_exact_method_path = bool(candidates)
        if not candidates:
            candidates = targets_by_canonical_method_path.get(
                (endpoint.method.upper(), _canonical_path(endpoint.path)), []
            )
        if not candidates:
            unmatched.append(endpoint)
            continue
        if len(candidates) != 1:
            ambiguous.append(endpoint)
            continue
        target = candidates[0]
        if matched_exact_service:
            matched_by_service += 1
        elif matched_exact_method_path:
            matched_by_unique_method_path += 1
        else:
            matched_by_canonical_path += 1
        matched.append(
            endpoint.model_copy(
                update={
                    "id": target.interface_id,
                    "workspace_id": target.workspace_id,
                    "project": target.project,
                    "method": target.method,
                    "path": target.path,
                    "sibling_actions": {},
                    "family_size": 1,
                }
            )
        )

    print(f"source_workspace={source_workspace}")
    print(f"target_workspace={target_workspace}")
    print(f"source_active={len(source_endpoints)}")
    print(f"target_interfaces={len(target_endpoints)}")
    print(f"exact_matches={len(matched)}")
    print(f"service_method_path_matches={matched_by_service}")
    print(f"unique_method_path_matches={matched_by_unique_method_path}")
    print(f"canonical_path_matches={matched_by_canonical_path}")
    print(f"unmatched={len(unmatched)}")
    print(f"ambiguous={len(ambiguous)}")
    for endpoint in unmatched[:20]:
        print(f"unmatched_item={endpoint.service} {endpoint.method} {endpoint.path}")
    for endpoint in ambiguous[:20]:
        print(f"ambiguous_item={endpoint.service} {endpoint.method} {endpoint.path}")

    if not args.apply:
        print("applied=false")
        return
    if ambiguous:
        raise RuntimeError("Refusing to apply while ambiguous exact identity matches exist")

    repository = PostgresEndpointRepository(target_url)
    profile = _source_profile(source_url, source_workspace)
    if profile is not None:
        repository.save_workspace_profile(
            profile.model_copy(
                update={
                    "workspace_id": target_workspace,
                    "name": target_workspace_name,
                }
            )
        )
    saved = repository.add_many(matched)
    family_rows = repository.rebuild_interface_families()
    print(f"saved={len(saved)}")
    print(f"family_rows_checked={family_rows}")
    print("applied=true")


if __name__ == "__main__":
    main()
