"""Batch rewrite interface names in interface forwarding records to readable Chinese names.

This is typically used once after improving normalization rules, to normalize
all historical interface records after the parsing logic has been adjusted.

Usage:
    python -m context_router.scripts.rewrite_interface_names --workspace-id <id>
    python -m context_router.scripts.rewrite_interface_names --all
"""

from __future__ import annotations

import argparse
import json

import psycopg
from psycopg.rows import dict_row

from context_router.config import Settings
from context_router.services.interface_forwarding import InterfaceForwardingService


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch rewrite interface forwarding names.")
    parser.add_argument("--workspace-id", help="只重写指定工作空间的接口名称")
    parser.add_argument("--service-id", help="配合 workspace-id 使用，只重写该服务")
    parser.add_argument("--path-prefix", help="只重写指定路径前缀，例如 /basic-api/")
    parser.add_argument(
        "--all",
        action="store_true",
        help="重写所有工作空间的接口名称",
    )
    return parser.parse_args()


def _fetch_workspace_ids(cursor: psycopg.Cursor[dict[str, str]]) -> list[str]:
    cursor.execute("SELECT DISTINCT workspace_id FROM interface_forwarding_services")
    return [str(item["workspace_id"]) for item in cursor.fetchall()]


def main() -> None:
    args = _parse_args()
    settings = Settings()
    if not settings.database_url:
        raise SystemExit("CONTEXT_ROUTER_DATABASE_URL 未配置，无法重命名历史接口")

    service = InterfaceForwardingService(settings.database_url)
    total_targets = 0
    total_updated = 0
    workspace_ids: list[str]

    if args.all:
        with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                workspace_ids = _fetch_workspace_ids(cursor)
        if not workspace_ids:
            raise SystemExit("当前库中未找到接口转发记录")

        for workspace_id in workspace_ids:
            result = service.rewrite_names(workspace_id)
            total_targets += result["total"]
            total_updated += result["updated"]

        print(
            json.dumps(
                {
                    "mode": "all",
                    "workspace_count": len(workspace_ids),
                    "total": total_targets,
                    "updated": total_updated,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if not args.workspace_id:
        raise SystemExit("必须指定 --workspace-id，或使用 --all")

    result = service.rewrite_names(
        args.workspace_id,
        service_id=args.service_id,
        path_prefix=args.path_prefix,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
