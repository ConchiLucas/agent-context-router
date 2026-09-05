"""Publish business semantics and source-backed table effects for MTP API routes."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from context_router.config import Settings
from context_router.services.interface_semantics import (
    BasicApiSourceAnalyzer,
    DeclarationApiSourceAnalyzer,
    DeclarationInterfaceApiSourceAnalyzer,
    ExternalInterfaceApiSourceAnalyzer,
    HighwayApiSourceAnalyzer,
    JobClientApiSourceAnalyzer,
    LineApiSourceAnalyzer,
    MessageApiSourceAnalyzer,
    OperationApiSourceAnalyzer,
    OrderApiSourceAnalyzer,
    RailwayApiSourceAnalyzer,
    SettlementApiSourceAnalyzer,
    ShippingApiSourceAnalyzer,
    TraceApiSourceAnalyzer,
    WebAdminApiSourceAnalyzer,
)

DEFAULT_WORKSPACE_ROOT = Path("/workspace/company_workforce/panzhihua_dev_workforce")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--service", default="c12-mtp")
    parser.add_argument(
        "--module",
        choices=(
            "order",
            "line",
            "basic",
            "highway",
            "railway",
            "shipping",
            "settlement",
            "declaration",
            "declaration-interface",
            "operation",
            "message",
            "external-interface",
            "job-client",
            "trace",
            "web",
        ),
        default="order",
    )
    parser.add_argument("--path-prefix")
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    args = parser.parse_args()
    if not args.path_prefix:
        args.path_prefix = f"/{args.module}-api/"
    return args


def _unique(*collections: object) -> list[str]:
    values: list[str] = []
    for collection in collections:
        if not isinstance(collection, (list, tuple)):
            continue
        for value in collection:
            normalized = str(value).strip()
            if normalized and normalized not in values:
                values.append(normalized)
    return values


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> None:
    args = _parse_args()
    settings = Settings()
    if not settings.database_url:
        raise SystemExit("CONTEXT_ROUTER_DATABASE_URL 未配置")
    analyzers = {
        "order": OrderApiSourceAnalyzer,
        "line": LineApiSourceAnalyzer,
        "basic": BasicApiSourceAnalyzer,
        "highway": HighwayApiSourceAnalyzer,
        "railway": RailwayApiSourceAnalyzer,
        "shipping": ShippingApiSourceAnalyzer,
        "settlement": SettlementApiSourceAnalyzer,
        "declaration": DeclarationApiSourceAnalyzer,
        "declaration-interface": DeclarationInterfaceApiSourceAnalyzer,
        "operation": OperationApiSourceAnalyzer,
        "message": MessageApiSourceAnalyzer,
        "external-interface": ExternalInterfaceApiSourceAnalyzer,
        "job-client": JobClientApiSourceAnalyzer,
        "trace": TraceApiSourceAnalyzer,
        "web": WebAdminApiSourceAnalyzer,
    }
    analyzer = analyzers[args.module](args.workspace_root)
    counters: Counter[str] = Counter()
    missing_controllers: list[str] = []
    missing_methods: list[str] = []
    no_table_effects: list[str] = []
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT interface.id, interface.name, interface.path, interface.method,
                       interface.description, interface.controller_name,
                       interface.operation_id, interface.crud_type,
                       profile.business_entity, profile.business_action,
                       profile.business_scenario, profile.aliases,
                       profile.positive_examples, profile.negative_examples,
                       profile.source, profile.confidence, profile.manual_locked
                FROM interface_forwarding_interfaces interface
                JOIN interface_forwarding_services service
                  ON service.id=interface.service_id
                LEFT JOIN interface_forwarding_intent_profiles profile
                  ON profile.interface_id=interface.id
                WHERE interface.workspace_id=%s AND service.name=%s
                  AND interface.path LIKE %s
                ORDER BY interface.path, interface.method
                """,
                (args.workspace, args.service, f"{args.path_prefix}%"),
            )
            rows = list(cursor.fetchall())
            for row in rows:
                interface_id = str(row["id"])
                analysis = analyzer.analyze(
                    controller_name=str(row["controller_name"] or ""),
                    path=str(row["path"]),
                    method=str(row["method"]),
                    interface_name=str(row["name"]),
                    existing_crud_type=(
                        str(row["crud_type"] or "unknown")
                        if bool(row["manual_locked"])
                        else "unknown"
                    ),
                    operation_id=str(row["operation_id"] or ""),
                )
                counters["interfaces"] += 1
                counters[f"crud_{analysis.crud_type}"] += 1
                if not analysis.controller_found:
                    missing_controllers.append(str(row["controller_name"] or row["path"]))
                elif not analysis.controller_method:
                    missing_methods.append(str(row["path"]))
                if not analysis.effects:
                    no_table_effects.append(str(row["path"]))
                cursor.execute(
                    """
                    UPDATE interface_forwarding_interfaces
                    SET crud_type=%s,
                        description=CASE WHEN description=''
                            THEN %s ELSE description END,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=%s
                    """,
                    (analysis.crud_type, analysis.business_scenario, interface_id),
                )
                if not bool(row["manual_locked"]):
                    entity = str(row["business_entity"] or analysis.business_entity)
                    action = str(row["business_action"] or analysis.business_action)
                    scenario = str(row["business_scenario"] or analysis.business_scenario)
                    aliases = _unique(row["aliases"], analysis.aliases)
                    examples = _unique(row["positive_examples"], analysis.positive_examples)
                    negatives = _unique(row["negative_examples"])
                    profile_payload = {
                        "entity": entity,
                        "action": action,
                        "scenario": scenario,
                        "aliases": aliases,
                        "examples": examples,
                        "controller_method": analysis.controller_method,
                    }
                    cursor.execute(
                        """
                        INSERT INTO interface_forwarding_intent_profiles
                            (interface_id, business_entity, business_action,
                             business_scenario, aliases, positive_examples,
                             negative_examples, source, confidence, manual_locked,
                             source_fingerprint)
                        VALUES (%s, %s, %s, %s, %s, %s, %s,
                                'generated', %s, false, %s)
                        ON CONFLICT (interface_id) DO UPDATE SET
                            business_entity=EXCLUDED.business_entity,
                            business_action=EXCLUDED.business_action,
                            business_scenario=EXCLUDED.business_scenario,
                            aliases=EXCLUDED.aliases,
                            positive_examples=EXCLUDED.positive_examples,
                            negative_examples=EXCLUDED.negative_examples,
                            confidence=GREATEST(
                                interface_forwarding_intent_profiles.confidence,
                                EXCLUDED.confidence
                            ),
                            source_fingerprint=EXCLUDED.source_fingerprint,
                            updated_at=CURRENT_TIMESTAMP
                        WHERE NOT interface_forwarding_intent_profiles.manual_locked
                        """,
                        (
                            interface_id,
                            entity,
                            action,
                            scenario,
                            Jsonb(aliases),
                            Jsonb(examples),
                            Jsonb(negatives),
                            90 if analysis.controller_method else 65,
                            _fingerprint(profile_payload),
                        ),
                    )
                    counters["profiles"] += 1
                cursor.execute(
                    """
                    DELETE FROM interface_forwarding_table_effects
                    WHERE interface_id=%s
                      AND evidence_type IN ('source_scan', 'convention')
                    """,
                    (interface_id,),
                )
                for effect in analysis.effects:
                    effect_payload = {
                        "interface_id": interface_id,
                        "table_name": effect.table_name,
                        "effect_type": effect.effect_type,
                        "source_method": effect.source_method,
                        "call_path": effect.call_path,
                        "sql_statement_id": effect.sql_statement_id,
                    }
                    cursor.execute(
                        """
                        INSERT INTO interface_forwarding_table_effects
                            (id, interface_id, database_key, schema_name,
                             table_name, effect_type, response_contribution,
                             source_file, source_class, source_method,
                             sql_statement_id, call_path, evidence_type,
                             confidence, source_fingerprint)
                        VALUES (%s, %s, 'c12_mtp_db', '', %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (interface_id, database_key, schema_name,
                                     table_name, effect_type) DO NOTHING
                        """,
                        (
                            str(uuid4()),
                            interface_id,
                            effect.table_name,
                            effect.effect_type,
                            effect.response_contribution,
                            effect.source_file,
                            effect.source_class,
                            effect.source_method,
                            effect.sql_statement_id,
                            Jsonb(list(effect.call_path)),
                            effect.evidence_type,
                            effect.confidence,
                            _fingerprint(effect_payload),
                        ),
                    )
                    counters["table_effects"] += cursor.rowcount
        connection.commit()
    print(
        {
            "workspace_id": args.workspace,
            "service": args.service,
            "module": args.module,
            "path_prefix": args.path_prefix,
            "counts": dict(sorted(counters.items())),
            "missing_controllers": sorted(set(missing_controllers)),
            "missing_methods": missing_methods,
            "without_local_table_effects": no_table_effects,
        }
    )


if __name__ == "__main__":
    main()
