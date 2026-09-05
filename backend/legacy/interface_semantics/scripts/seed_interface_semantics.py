"""Publish curated interface semantics and table effects from inspected source code.

The first slice covers ``cs_dsly_order_entrusted``.  Declarations are keyed by
service/path/method instead of runtime interface IDs, so re-importing OpenAPI does
not invalidate them.  Manual intent profiles remain authoritative.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from context_router.config import Settings

WORKSPACE_SOURCE_PREFIX = "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz/"
ADMIN_SERVICE = (
    WORKSPACE_SOURCE_PREFIX + "src/main/java/com/chinaservices/dsly/order/module/entrusted/service/"
    "OrderEntrustedAdminService.java"
)
PORTAL_SERVICE = (
    WORKSPACE_SOURCE_PREFIX + "src/main/java/com/chinaservices/dsly/order/module/entrusted/service/"
    "OrderEntrustedPortalService.java"
)
QUOTE_ADMIN_SERVICE = (
    WORKSPACE_SOURCE_PREFIX
    + "src/main/java/com/chinaservices/dsly/order/module/entrustedquote/service/"
    "OrderEntrustedQuoteAdminService.java"
)
QUOTE_PORTAL_SERVICE = (
    WORKSPACE_SOURCE_PREFIX
    + "src/main/java/com/chinaservices/dsly/order/module/entrustedquote/service/"
    "OrderEntrustedQuotePortalService.java"
)


@dataclass(frozen=True, slots=True)
class InterfaceSemanticSeed:
    path: str
    controller_class: str
    controller_method: str
    service_method: str
    crud_type: str
    business_entity: str
    business_action: str
    business_scenario: str
    aliases: tuple[str, ...]
    positive_examples: tuple[str, ...]
    effect_type: str
    response_contribution: str
    source_file: str
    sql_statement_id: str = ""
    method: str = "POST"

    @property
    def call_path(self) -> list[str]:
        return [
            f"{self.controller_class}.{self.controller_method}",
            self.service_method,
            f"cs_dsly_order_entrusted:{self.effect_type}",
        ]

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()


def _seed(
    path: str,
    *,
    controller_class: str,
    controller_method: str,
    service_method: str,
    crud_type: str,
    entity: str,
    action: str,
    scenario: str,
    aliases: tuple[str, ...],
    examples: tuple[str, ...],
    effect: str,
    returned: bool = False,
    source_file: str,
    sql_id: str = "",
) -> InterfaceSemanticSeed:
    return InterfaceSemanticSeed(
        path=path,
        controller_class=controller_class,
        controller_method=controller_method,
        service_method=service_method,
        crud_type=crud_type,
        business_entity=entity,
        business_action=action,
        business_scenario=scenario,
        aliases=aliases,
        positive_examples=examples,
        effect_type=effect,
        response_contribution="returned" if returned else "none",
        source_file=source_file,
        sql_statement_id=sql_id,
    )


SEEDS: tuple[InterfaceSemanticSeed, ...] = (
    _seed(
        "/order-api/admin/entrusted/page",
        controller_class="OrderEntrustedAdminController",
        controller_method="page",
        service_method="OrderEntrustedAdminService.page",
        crud_type="read",
        entity="委托需求",
        action="分页查询",
        scenario="运营端按条件分页查询委托需求",
        aliases=("查询委托需求", "委托需求列表", "运营端委托需求分页"),
        examples=("查询一条委托需求", "分页查看运营端委托需求"),
        effect="select",
        returned=True,
        source_file=ADMIN_SERVICE,
        sql_id="order_entrusted_query_getPageList",
    ),
    _seed(
        "/order-api/admin/entrusted/getById/{id}",
        controller_class="OrderEntrustedAdminController",
        controller_method="getById",
        service_method="OrderEntrustedAdminService.getById",
        crud_type="read",
        entity="委托需求",
        action="按ID查询",
        scenario="运营端查询一条委托需求详情",
        aliases=("委托需求详情", "按ID查询委托需求", "查看委托需求"),
        examples=("查看委托需求 123 的详情",),
        effect="select",
        returned=True,
        source_file=ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/admin/entrusted/getQuoteById/{id}",
        controller_class="OrderEntrustedAdminController",
        controller_method="getQuoteById",
        service_method="OrderEntrustedAdminService.getQuoteById",
        crud_type="read",
        entity="委托需求报价资料",
        action="查询报价资料",
        scenario="运营端报价前读取委托需求、货物和线路资料",
        aliases=("查询委托报价资料", "报价前查询委托需求", "需求报价线路"),
        examples=("查询这条委托需求的报价资料",),
        effect="select",
        returned=True,
        source_file=ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/admin/entrusted/save",
        controller_class="OrderEntrustedAdminController",
        controller_method="save",
        service_method="OrderEntrustedAdminService.saveOrUpdateEntrusted",
        crud_type="update",
        entity="委托需求",
        action="保存或更新",
        scenario="运营端保存委托需求并同步货物、箱信息和地址",
        aliases=("保存委托需求", "更新委托需求", "编辑委托需求"),
        examples=("修改这条委托需求", "保存运营端委托需求"),
        effect="upsert",
        source_file=ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/admin/entrusted/deleteByIds/{ids}",
        controller_class="OrderEntrustedAdminController",
        controller_method="deleteById",
        service_method="OrderEntrustedAdminService.delete",
        crud_type="delete",
        entity="委托需求",
        action="批量删除",
        scenario="运营端删除允许删除的手工委托需求",
        aliases=("删除委托需求", "批量删除委托需求"),
        examples=("删除这条待报价委托需求",),
        effect="delete",
        source_file=ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/admin/entrusted/generatePlanFromContract",
        controller_class="OrderEntrustedAdminController",
        controller_method="generatePlanFromContract",
        service_method="OrderEntrustedAdminService.generatePlanFromContract",
        crud_type="create",
        entity="委托需求作业计划",
        action="根据合同生成作业计划",
        scenario="根据已关联合同的委托需求生成主作业计划并更新委托状态",
        aliases=("委托需求生成作业计划", "根据合同生成计划"),
        examples=("给这条委托需求生成作业计划",),
        effect="update",
        source_file=ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/portal/entrusted/getPortalPage",
        controller_class="OrderEntrustedPortalController",
        controller_method="getPortalPage",
        service_method="OrderEntrustedPortalService.page",
        crud_type="read",
        entity="委托需求",
        action="分页查询",
        scenario="门户端分页查询当前货主的委托需求",
        aliases=("货主委托需求列表", "门户委托需求分页", "查询我的委托需求"),
        examples=("查询当前货主的委托需求",),
        effect="select",
        returned=True,
        source_file=PORTAL_SERVICE,
        sql_id="order_entrusted_query_getPageList",
    ),
    _seed(
        "/order-api/portal/entrusted/getById/{id}",
        controller_class="OrderEntrustedPortalController",
        controller_method="getById",
        service_method="OrderEntrustedPortalService.getById",
        crud_type="read",
        entity="委托需求",
        action="按ID查询",
        scenario="门户端查询当前货主的一条委托需求详情",
        aliases=("门户委托需求详情", "货主查看委托需求"),
        examples=("货主查看这条委托需求详情",),
        effect="select",
        returned=True,
        source_file=PORTAL_SERVICE,
    ),
    _seed(
        "/order-api/portal/entrusted/getQuoteById/{id}",
        controller_class="OrderEntrustedPortalController",
        controller_method="getQuoteById",
        service_method="OrderEntrustedPortalService.getQuoteById",
        crud_type="read",
        entity="委托需求报价资料",
        action="查询报价资料",
        scenario="门户端读取委托需求的报价线路和货物资料",
        aliases=("门户查询委托报价", "货主查看报价资料"),
        examples=("查看我的委托需求报价资料",),
        effect="select",
        returned=True,
        source_file=PORTAL_SERVICE,
    ),
    _seed(
        "/order-api/portal/entrusted/saveEntrusted",
        controller_class="OrderEntrustedPortalController",
        controller_method="savePortalEntrusted",
        service_method="OrderEntrustedPortalService.saveOrUpdateEntrusted",
        crud_type="create",
        entity="委托需求",
        action="新增",
        scenario="门户端货主创建委托需求并保存货物、箱信息和地址",
        aliases=("新增委托需求", "创建委托需求", "货主发起委托需求"),
        examples=("帮我创建一条委托需求", "货主发起新的运输委托"),
        effect="upsert",
        source_file=PORTAL_SERVICE,
    ),
    _seed(
        "/order-api/portal/entrusted/deleteByIds/{ids}",
        controller_class="OrderEntrustedPortalController",
        controller_method="deleteById",
        service_method="OrderEntrustedPortalService.delete",
        crud_type="delete",
        entity="委托需求",
        action="批量删除",
        scenario="门户端删除当前货主的委托需求",
        aliases=("货主删除委托需求", "门户批量删除委托需求"),
        examples=("删除我的这条委托需求",),
        effect="delete",
        source_file=PORTAL_SERVICE,
    ),
    _seed(
        "/order-api/admin/entrusted/quote/getByEntrustedId/{id}",
        controller_class="OrderEntrustedQuoteAdminController",
        controller_method="getById",
        service_method="OrderEntrustedQuoteAdminService.getByEntrustedId",
        crud_type="read",
        entity="委托需求报价",
        action="按委托需求查询报价",
        scenario="运营端按委托需求ID查询委托资料和当前报价",
        aliases=("查询委托需求报价", "按需求查询报价", "委托报价详情"),
        examples=("查询这条委托需求当前的报价",),
        effect="select",
        returned=True,
        source_file=QUOTE_ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/admin/entrusted/quote/getEntrustedQuoteById/{id}",
        controller_class="OrderEntrustedQuoteAdminController",
        controller_method="getEntrustedQuoteById",
        service_method="OrderEntrustedQuoteAdminService.getEntrustedQuoteById",
        crud_type="read",
        entity="委托需求报价",
        action="查询再次报价资料",
        scenario="运营端读取委托需求和既有报价用于再次报价",
        aliases=("再次报价详情", "查询委托报价线路", "重新报价资料"),
        examples=("查询这条需求的再次报价资料",),
        effect="select",
        returned=True,
        source_file=QUOTE_ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/admin/entrusted/quote/save",
        controller_class="OrderEntrustedQuoteAdminController",
        controller_method="save",
        service_method="OrderEntrustedQuoteAdminService.saveQuote",
        crud_type="create",
        entity="委托需求报价",
        action="发起报价",
        scenario="运营人员为委托需求创建报价方案并更新委托报价状态",
        aliases=("发起委托需求报价", "提交委托报价", "创建委托报价", "保存委托报价"),
        examples=("为这条委托需求发起报价", "给委托需求提交一个报价方案"),
        effect="update",
        source_file=QUOTE_ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/admin/entrusted/quote/edit",
        controller_class="OrderEntrustedQuoteAdminController",
        controller_method="edit",
        service_method="OrderEntrustedQuoteAdminService.editQuote",
        crud_type="update",
        entity="委托需求报价",
        action="编辑报价",
        scenario="运营端编辑报价方案并同步委托需求预估运费",
        aliases=("修改委托报价", "编辑报价方案"),
        examples=("修改这条委托需求的报价",),
        effect="update",
        source_file=QUOTE_ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/admin/entrusted/quote/approval",
        controller_class="OrderEntrustedQuoteAdminController",
        controller_method="approval",
        service_method="OrderEntrustedQuoteAdminService.changeQuoteStatus",
        crud_type="update",
        entity="委托需求报价",
        action="提交审批",
        scenario="提交委托报价审批并同步委托需求状态",
        aliases=("提交报价审批", "委托报价送审"),
        examples=("把这条委托报价提交审批",),
        effect="update",
        source_file=QUOTE_ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/admin/entrusted/quote/cancelApproval",
        controller_class="OrderEntrustedQuoteAdminController",
        controller_method="cancelApproval",
        service_method="OrderEntrustedQuoteAdminService.changeQuoteStatus",
        crud_type="update",
        entity="委托需求报价",
        action="取消审批",
        scenario="取消委托报价审批并同步委托需求状态",
        aliases=("撤回报价审批", "取消委托报价审批"),
        examples=("撤回这条报价的审批",),
        effect="update",
        source_file=QUOTE_ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/admin/entrusted/quote/quoteApprove",
        controller_class="OrderEntrustedQuoteAdminController",
        controller_method="quoteApprove",
        service_method="OrderEntrustedQuoteAdminService.changeQuoteStatus",
        crud_type="update",
        entity="委托需求报价",
        action="审批通过",
        scenario="通过委托报价审批并同步委托需求状态",
        aliases=("通过委托报价", "报价审批通过"),
        examples=("通过这条委托报价",),
        effect="update",
        source_file=QUOTE_ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/admin/entrusted/quote/quoteReject",
        controller_class="OrderEntrustedQuoteAdminController",
        controller_method="quoteReject",
        service_method="OrderEntrustedQuoteAdminService.changeQuoteStatus",
        crud_type="update",
        entity="委托需求报价",
        action="审批驳回",
        scenario="驳回委托报价审批并同步委托需求状态",
        aliases=("驳回委托报价", "报价审批拒绝"),
        examples=("驳回这条委托报价",),
        effect="update",
        source_file=QUOTE_ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/admin/entrusted/quote/deleteByIds/{ids}",
        controller_class="OrderEntrustedQuoteAdminController",
        controller_method="deleteById",
        service_method="OrderEntrustedQuoteAdminService.deleteByIds",
        crud_type="delete",
        entity="委托需求报价",
        action="删除报价",
        scenario="删除报价记录并回退委托需求的报价轮次和状态",
        aliases=("删除委托报价", "批量删除报价"),
        examples=("删除这条委托需求报价",),
        effect="update",
        source_file=QUOTE_ADMIN_SERVICE,
    ),
    _seed(
        "/order-api/portal/entrusted/quote/getByEntrustedId/{id}",
        controller_class="OrderEntrustedQuotePortalController",
        controller_method="getById",
        service_method="OrderEntrustedQuotePortalService.getByEntrustedId",
        crud_type="read",
        entity="委托需求报价",
        action="按委托需求查询报价",
        scenario="门户端按委托需求ID查询需求资料和当前报价",
        aliases=("货主查询委托报价", "门户委托报价详情"),
        examples=("货主查看这条需求的报价",),
        effect="select",
        returned=True,
        source_file=QUOTE_PORTAL_SERVICE,
    ),
    _seed(
        "/order-api/portal/entrusted/quote/getEntrustedQuoteById/{id}",
        controller_class="OrderEntrustedQuotePortalController",
        controller_method="getEntrustedQuoteById",
        service_method="OrderEntrustedQuotePortalService.getEntrustedQuoteById",
        crud_type="read",
        entity="委托需求报价",
        action="查询报价线路",
        scenario="门户端读取委托需求和报价线路详情",
        aliases=("货主查看报价线路", "门户查询委托报价资料"),
        examples=("查看这条报价的线路详情",),
        effect="select",
        returned=True,
        source_file=QUOTE_PORTAL_SERVICE,
    ),
    _seed(
        "/order-api/portal/entrusted/quote/shipper/approve",
        controller_class="OrderEntrustedQuotePortalController",
        controller_method="shipperApprove",
        service_method="OrderEntrustedQuotePortalService.shipperApprove",
        crud_type="update",
        entity="委托需求报价",
        action="货主同意报价",
        scenario="货主接受报价并更新委托需求状态和合同信息",
        aliases=("货主接受报价", "同意委托报价"),
        examples=("货主同意这条报价",),
        effect="update",
        source_file=QUOTE_PORTAL_SERVICE,
    ),
    _seed(
        "/order-api/portal/entrusted/quote/shipper/reject",
        controller_class="OrderEntrustedQuotePortalController",
        controller_method="shipperReject",
        service_method="OrderEntrustedQuotePortalService.shipperReject",
        crud_type="update",
        entity="委托需求报价",
        action="货主驳回报价",
        scenario="货主驳回报价并更新委托需求状态",
        aliases=("货主拒绝报价", "驳回委托报价"),
        examples=("货主拒绝这条报价",),
        effect="update",
        source_file=QUOTE_PORTAL_SERVICE,
    ),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, help="Workspace ID")
    parser.add_argument("--service", default="c12-mtp")
    parser.add_argument("--table", default="cs_dsly_order_entrusted")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.table != "cs_dsly_order_entrusted":
        raise SystemExit("首版只支持 cs_dsly_order_entrusted")
    settings = Settings()
    if not settings.database_url:
        raise SystemExit("CONTEXT_ROUTER_DATABASE_URL 未配置")

    matched = 0
    missing: list[str] = []
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            for seed in SEEDS:
                cursor.execute(
                    """
                    SELECT interface.id
                    FROM interface_forwarding_interfaces interface
                    JOIN interface_forwarding_services service
                      ON service.id=interface.service_id
                    WHERE interface.workspace_id=%s AND service.name=%s
                      AND interface.path=%s AND interface.method=%s
                    """,
                    (args.workspace, args.service, seed.path, seed.method),
                )
                row = cursor.fetchone()
                if row is None:
                    missing.append(seed.path)
                    continue
                interface_id = str(row["id"])
                cursor.execute(
                    """
                    UPDATE interface_forwarding_interfaces
                    SET crud_type=%s, updated_at=CURRENT_TIMESTAMP
                    WHERE id=%s
                    """,
                    (seed.crud_type, interface_id),
                )
                cursor.execute(
                    """
                    INSERT INTO interface_forwarding_intent_profiles
                        (interface_id, business_entity, business_action,
                         business_scenario, aliases, positive_examples,
                         negative_examples, source, confidence, manual_locked,
                         source_fingerprint)
                    VALUES (%s, %s, %s, %s, %s, %s, '[]'::jsonb,
                            'generated', 95, false, %s)
                    ON CONFLICT (interface_id) DO UPDATE SET
                        business_entity=EXCLUDED.business_entity,
                        business_action=EXCLUDED.business_action,
                        business_scenario=EXCLUDED.business_scenario,
                        aliases=EXCLUDED.aliases,
                        positive_examples=EXCLUDED.positive_examples,
                        source='generated', confidence=EXCLUDED.confidence,
                        source_fingerprint=EXCLUDED.source_fingerprint,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE NOT interface_forwarding_intent_profiles.manual_locked
                    """,
                    (
                        interface_id,
                        seed.business_entity,
                        seed.business_action,
                        seed.business_scenario,
                        Jsonb(list(seed.aliases)),
                        Jsonb(list(seed.positive_examples)),
                        seed.fingerprint,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO interface_forwarding_table_effects
                        (id, interface_id, database_key, schema_name, table_name,
                         effect_type, response_contribution, source_file,
                         source_class, source_method, sql_statement_id, call_path,
                         evidence_type, confidence, source_fingerprint)
                    VALUES (%s, %s, 'c12_mtp_db', '', %s, %s, %s, %s, %s,
                            %s, %s, %s, 'source_code', 95, %s)
                    ON CONFLICT (interface_id, database_key, schema_name,
                                 table_name, effect_type) DO UPDATE SET
                        response_contribution=EXCLUDED.response_contribution,
                        source_file=EXCLUDED.source_file,
                        source_class=EXCLUDED.source_class,
                        source_method=EXCLUDED.source_method,
                        sql_statement_id=EXCLUDED.sql_statement_id,
                        call_path=EXCLUDED.call_path,
                        evidence_type=EXCLUDED.evidence_type,
                        confidence=EXCLUDED.confidence,
                        source_fingerprint=EXCLUDED.source_fingerprint,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        str(uuid4()),
                        interface_id,
                        args.table,
                        seed.effect_type,
                        seed.response_contribution,
                        seed.source_file,
                        seed.service_method.split(".", 1)[0],
                        seed.service_method,
                        seed.sql_statement_id,
                        Jsonb(seed.call_path),
                        seed.fingerprint,
                    ),
                )
                matched += 1
    print(
        {
            "workspace_id": args.workspace,
            "service": args.service,
            "table": args.table,
            "matched": matched,
            "missing": missing,
        }
    )


if __name__ == "__main__":
    main()
