"""Synchronize interface controller names and short Chinese descriptions from Java source."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from context_router.config import Settings
from context_router.services.interface_forwarding import InterfaceForwardingService


@dataclass(frozen=True)
class JavaController:
    name: str
    tag: str
    tag_description: str
    comment: str


def _contains_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _clean_comment(block: str) -> str:
    for raw_line in block.splitlines():
        line = re.sub(r"^\s*/?\*+/?\s?", "", raw_line).strip()
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line or line.startswith("@"):
            continue
        if re.fullmatch(r"[\d\-: /.]+", line) or re.fullmatch(r"[A-Za-z.]+", line):
            continue
        if _contains_chinese(line):
            return line
    return ""


def _annotation_value(annotation: str, key: str) -> str:
    matched = re.search(rf'\b{key}\s*=\s*"([^"]+)"', annotation)
    return matched.group(1).strip() if matched else ""


def _scan_java_controllers(root: Path) -> dict[str, JavaController]:
    controllers: dict[str, JavaController] = {}
    for java_path in root.rglob("*.java"):
        text = java_path.read_text(errors="ignore")
        for class_match in re.finditer(
            r"\bpublic\s+(?:abstract\s+)?class\s+(\w*Controller)\b", text
        ):
            class_name = class_match.group(1)
            prefix = text[: class_match.start()]
            boundary = max(prefix.rfind("}"), prefix.rfind(";"))
            local = prefix[boundary + 1 :]
            annotations = re.findall(r"@Tag\s*\((.*?)\)", local, re.S)
            annotation = annotations[-1] if annotations else ""
            comments = re.findall(r"/\*\*(.*?)\*/", local, re.S)
            controllers[class_name] = JavaController(
                name=class_name,
                tag=_annotation_value(annotation, "name"),
                tag_description=_annotation_value(annotation, "description"),
                comment=_clean_comment(comments[-1]) if comments else "",
            )
    return controllers


def _normalized_tag(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value).lower()


def _resolve_from_source(
    current: str,
    path: str,
    controllers: dict[str, JavaController],
) -> str:
    if current in controllers:
        return current
    case_matched = next((name for name in controllers if name.lower() == current.lower()), "")
    if case_matched:
        return case_matched
    tag = current.removesuffix("Controller")
    matches = [
        item.name
        for item in controllers.values()
        if item.tag and _normalized_tag(item.tag) == _normalized_tag(tag)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        path_tokens = set(re.findall(r"[a-z]+", path.lower()))
        return max(
            matches,
            key=lambda name: len(path_tokens & set(re.findall(r"[a-z]+", name.lower()))),
        )
    return current


TOKEN_CN = {
    "account": "账户", "address": "地址", "administrative": "行政", "advance": "预付",
    "appointment": "预约", "approval": "审批", "attachment": "附件", "auth": "认证",
    "bid": "投标", "booking": "订舱", "box": "箱码", "cargo": "货物",
    "carrier": "承运商", "category": "分类", "collection": "收款", "commodity": "商品",
    "common": "公共", "company": "企业", "config": "配置", "confirmation": "确认",
    "consortium": "联合体", "container": "集装箱", "contract": "合同", "customer": "客户",
    "dashboard": "工作台", "data": "数据", "declaration": "报关", "decrypt": "解密",
    "deposit": "保证金", "dispatch": "调度", "division": "部门", "document": "单证",
    "driver": "司机", "email": "邮件", "enterprise": "企业", "entrust": "委托",
    "entrusted": "委托", "evaluation": "评价", "expense": "费用", "external": "外部接口",
    "fee": "费用", "file": "文件", "footer": "页脚", "fund": "资金",
    "goods": "货物", "government": "政务填报", "group": "群组", "history": "历史",
    "inbound": "入库", "information": "信息", "inventory": "库存", "invoice": "发票",
    "job": "调度任务", "level": "等级", "log": "日志", "manifest": "舱单",
    "map": "地图", "member": "会员", "menu": "菜单", "message": "消息",
    "monthly": "月度", "node": "节点", "notice": "公告", "operation": "运营",
    "order": "订单", "outbound": "出库", "overview": "概览", "owner": "货主",
    "page": "页面", "park": "园区", "payable": "应付账单", "payment": "付款",
    "permission": "权限", "plan": "计划", "port": "港口", "prepayment": "预付款",
    "price": "价格", "product": "产品", "qualification": "资质", "quarantine": "检疫",
    "railway": "铁路", "receipt": "收款", "receivable": "应收账单", "record": "记录",
    "relation": "关联", "report": "报表", "robot": "机器人", "role": "角色",
    "route": "线路", "sales": "销项", "select": "下拉数据", "settlement": "结算",
    "ship": "船舶", "shipper": "托运人", "shipping": "水运", "site": "站点",
    "sms": "短信", "station": "场站", "statistics": "统计", "stocktake": "盘点",
    "supplier": "供应商", "task": "任务", "template": "模板", "trace": "跟踪",
    "track": "轨迹", "transport": "运输", "user": "用户", "vehicle": "车辆",
    "verification": "核销", "warehouse": "仓库", "warning": "预警", "waybill": "运单",
    "work": "作业", "workbench": "工作台",
}


def _scope(controller_name: str, path: str) -> str:
    lower_name = controller_name.lower()
    lower_path = path.lower()
    role = ""
    if "/admin/" in lower_path or lower_name.endswith("admincontroller"):
        role = "运营端"
    elif "/portal/" in lower_path or lower_name.endswith("portalcontroller"):
        role = "门户端"
    if "mini" in lower_name or "/mini/" in lower_path:
        role = f"{role}小程序" if role else "小程序"
    if "noauth" in lower_name:
        role = f"{role}免登录" if role else "免登录"
    if lower_name.startswith("remote") or "remote" in lower_name:
        role = f"{role}内部调用" if role else "内部调用"

    module = ""
    for prefix, label in (
        ("highway", "公路"), ("railway", "铁路"), ("shipping", "水运"),
        ("declaration", "报关"), ("settlement", "结算"),
    ):
        if prefix in lower_name.removesuffix("controller") or lower_path.startswith(f"/{prefix}-api/"):
            module = label
            break
    return f"{role}{module}"


def _fallback_subject(controller_name: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", controller_name).split()
    ignored = {
        "controller", "admin", "portal", "remote", "no", "auth", "mini", "api",
        "highway", "railway", "shipping", "data", "basic",
    }
    translated = [TOKEN_CN[word.lower()] for word in words if word.lower() in TOKEN_CN and word.lower() not in ignored]
    return "".join(dict.fromkeys(translated)) or "业务接口"


def _description(
    source: JavaController | None,
    current: str,
    controller_name: str,
    path: str,
) -> str:
    special_descriptions = {
        "CustomSseEmitterController": "负责 SSE 实时连接、订阅和事件推送。",
        "OpenSysProxyController": "负责代理系统公共数据，以及消息、文件和任务中心接口。",
        "ContractAdminController": "负责运营端会员合同查询、配置及状态管理。",
        "ContractPortalController": "负责门户端会员合同查询。",
        "RemoteContractPortalController": "负责会员合同内部查询接口。",
        "OriginAdminController": "负责运营端报关原产地信息管理。",
        "OriginPortalController": "负责门户端报关原产地信息查询。",
        "TestController": "用于邮件发送等内部联调接口。",
    }
    if controller_name in special_descriptions:
        return special_descriptions[controller_name]
    candidates = []
    if source:
        candidates.extend([source.tag_description, source.comment, source.tag])
    candidates.append(current)
    raw = next(
        (
            value.strip()
            for value in candidates
            if value and _contains_chinese(value) and value.replace("相关接口", "").strip(" -")
        ),
        "",
    )
    if raw.startswith("负责") and raw.endswith("相关功能。"):
        raw = raw[2:-5]
        for label in ("运营端", "门户端", "小程序", "免登录", "内部调用", "公路", "铁路", "水运", "报关", "结算"):
            raw = raw.replace(label, "")
    raw = re.sub(r"[。.;；]+$", "", raw).strip()
    raw = re.sub(r"(?:相关)?接口$", "", raw).strip()
    raw = re.sub(r"(?:控制器|控制层)$", "", raw).strip()
    if not raw or len(re.findall(r"[\u4e00-\u9fff]", raw)) < 2:
        raw = _fallback_subject(controller_name)
    scope = _scope(controller_name, path)
    for label in ("运营端", "门户端", "小程序", "免登录", "内部调用", "公路", "铁路", "水运", "报关", "结算"):
        if label in raw:
            scope = scope.replace(label, "")
    if raw.startswith(("负责", "用于", "提供")):
        return f"{raw}。"
    for role in ("运营端", "门户端", "小程序", "免登录", "内部调用"):
        if raw.startswith(role):
            return f"负责{role}{scope}{raw[len(role):]}相关功能。"
    return f"负责{scope}{raw}相关功能。"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--service", action="append", required=True, metavar="NAME=SOURCE_ROOT")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = Settings()
    if not settings.database_url:
        raise SystemExit("CONTEXT_ROUTER_DATABASE_URL 未配置")
    sources = dict(item.split("=", 1) for item in args.service)
    catalogs = {name: _scan_java_controllers(Path(root)) for name, root in sources.items()}
    updated = 0
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT interface.id, interface.controller_name, interface.controller_description,
                       interface.path, service.name AS service_name
                FROM interface_forwarding_interfaces AS interface
                JOIN interface_forwarding_services AS service ON service.id = interface.service_id
                WHERE interface.workspace_id = %s AND service.name = ANY(%s)
                """,
                (args.workspace_id, list(sources)),
            )
            prepared: list[tuple[dict, str]] = []
            grouped: dict[tuple[str, str], list[dict]] = {}
            for row in cursor.fetchall():
                service_name = str(row["service_name"])
                path = str(row["path"])
                current_name = str(row["controller_name"] or "")
                normalized_name = InterfaceForwardingService._derive_source_controller_name(
                    service_name, current_name, path
                )
                normalized_name = _resolve_from_source(normalized_name, path, catalogs[service_name])
                prepared.append((row, normalized_name))
                grouped.setdefault((service_name, normalized_name), []).append(row)

            descriptions: dict[tuple[str, str], str] = {}
            for (service_name, normalized_name), group_rows in grouped.items():
                representative = max(
                    group_rows,
                    key=lambda item: (
                        "相关接口" not in str(item["controller_description"] or ""),
                        len(re.findall(r"[\u4e00-\u9fff]", str(item["controller_description"] or ""))),
                    ),
                )
                descriptions[(service_name, normalized_name)] = _description(
                    catalogs[service_name].get(normalized_name),
                    str(representative["controller_description"] or ""),
                    normalized_name,
                    str(representative["path"]),
                )

            for row, normalized_name in prepared:
                service_name = str(row["service_name"])
                normalized_description = descriptions[(service_name, normalized_name)]
                if (
                    normalized_name != str(row["controller_name"] or "")
                    or normalized_description != row["controller_description"]
                ):
                    cursor.execute(
                        """
                        UPDATE interface_forwarding_interfaces
                        SET controller_name = %s, controller_description = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (normalized_name, normalized_description, row["id"]),
                    )
                    updated += 1
    print({"workspace_id": args.workspace_id, "services": list(sources), "updated": updated})


if __name__ == "__main__":
    main()
