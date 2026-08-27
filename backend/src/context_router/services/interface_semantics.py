from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_CLASS_RE = re.compile(r"\b(?:class|interface)\s+(\w+)(?:\s+extends\s+(\w+))?")
_FIELD_RE = re.compile(
    r"\b(?:private|protected|public)\s+(?:static\s+)?(?:final\s+)?"
    r"([A-Za-z_$][\w.$]*)(?:\s*<[^;=]+>)?\s+(\w+)\s*(?:=[^;]+)?;"
)
_METHOD_RE = re.compile(
    r"^[ \t]*(?!(?:if|for|while|switch|catch|return|new|throw|else|do|try)\b)"
    r"(?:(?:public|protected|private|static|final|synchronized|default|strictfp)\s+)*"
    r"(?:<[^>{}\n]+>[ \t]+)?[A-Za-z_$][\w.$<>\[\], ?]*[ \t]+"
    r"([A-Za-z_$]\w*)[ \t]*\([^;{}]*\)[ \t\r\n]*"
    r"(?:throws[ \t]+[^{}\n]+)?[ \t\r\n]*\{",
    re.MULTILINE,
)
_MAPPING_RE = re.compile(
    r"@(?:Get|Post|Put|Delete|Patch|Request)Mapping\s*"
    r"(?:\(\s*(?:value\s*=\s*)?(?:\{\s*)?\"([^\"]*)\")?",
    re.DOTALL,
)
_MEMBER_CALL_RE = re.compile(r"\b([A-Za-z_$]\w*)\s*\.\s*([A-Za-z_$]\w*)\s*\(")
_BARE_CALL_RE = re.compile(r"(?<![.\w])([A-Za-z_$]\w*)\s*\(")
_BASE_CALL_RE = re.compile(
    r"(?<![.\w])"
    r"(findFirst|findById|find|page|list|query|count|exists|insert|batchInsert|"
    r"saveOrUpdate|batchUpdate|update|delete|remove)\s*\("
)
_SQL_CONSTANT_RE = re.compile(
    r"(?:public\s+static\s+final\s+)?String\s+(\w+)\s*=\s*\"([^\"]+)\""
)
_SQL_LITERAL_RE = re.compile(
    r"\bsqlExecutor\s*\.\s*"
    r"(?:page|findFirst|find|query|update|insert|delete)\s*"
    r"\([^;{}]*?\"([A-Za-z_$][\w.-]*)\"",
    re.DOTALL,
)
_SQL_TABLE_RE = re.compile(
    r"\b(?:from|join|update|into|delete\s+from)\s+([a-zA-Z_][\w.]*)",
    re.IGNORECASE,
)
_TABLE_RE = re.compile(r"@Table\s*\(\s*name\s*=\s*\"([^\"]+)\"[^)]*\)")
_SERVICE_MODEL_RE = re.compile(
    r"ModuleBaseServiceSupport\s*<\s*(\w+)\s*,\s*(\w+)",
    re.DOTALL,
)
_DAO_MODEL_RE = re.compile(r"ModuleBaseDaoSupport\s*<\s*(\w+)", re.DOTALL)
_JPA_DAO_MODEL_RE = re.compile(r"JpaRepository\s*<\s*(\w+)", re.DOTALL)


ORDER_CONTROLLER_ENTITIES: dict[str, str] = {
    "BookingApplicationAdminController": "订舱申请",
    "BookingApplicationPortalController": "订舱申请",
    "BookingApplicationConfirmAdminController": "订舱确认",
    "BookingApplicationConfirmPortalController": "订舱确认",
    "EntrustedOrderSettlementAdminController": "委托订单结算",
    "EntrustedOrderSettlementPortalController": "委托订单结算",
    "OrderAttachmentAdminController": "订单附件",
    "OrderAttachmentPortalController": "订单附件",
    "OrderCommonController": "订单公共数据",
    "OrderContainerAdminController": "订单箱信息",
    "OrderEntrustedAdminController": "委托需求",
    "OrderEntrustedPortalController": "委托需求",
    "OrderEntrustedOrderAdminController": "委托订单",
    "OrderEntrustedOrderPortalController": "委托订单",
    "OrderEntrustedQuoteAdminController": "委托需求报价",
    "OrderEntrustedQuotePortalController": "委托需求报价",
    "OrderFileController": "委托订单文件",
    "OrderNodeAdminController": "订单节点",
    "OrderNodePortalController": "订单节点",
    "OutboundBoxOrderAdminController": "出库箱订单",
    "OutboundOrderAdminController": "出库单",
    "WorkPlanAdminController": "作业计划",
    "WorkPlanPortalController": "作业计划",
    "entrustedOrderRelateAdminController": "委托订单关联",
}

LINE_CONTROLLER_ENTITIES: dict[str, str] = {
    "ApprovalHistoryAdminController": "线路审批历史",
    "ApprovalUserAdminController": "线路审批用户",
    "AttachmentController": "线路附件",
    "LineRolePermissionController": "线路角色权限",
    "RemoteRouteProductPortalController": "线路产品",
    "RemoteStationPortalController": "站点",
    "RouteAdminController": "线路",
    "RoutePortalController": "线路",
    "RouteCargoChargeAdminController": "线路货物费用",
    "RouteCargoChargePortalController": "线路货物费用",
    "RouteCargoChargeRangeAdminController": "线路货物费用区间",
    "RouteProductAdminController": "线路产品",
    "RouteProductNoAuthPortalController": "线路产品",
    "RouteProductPortalController": "线路产品",
    "RouteRailwayStationAdminController": "线路铁路站点",
    "RouteSnapshotQuoteAdminController": "线路快照报价",
    "RouteInquiryAdminController": "线路询价",
    "RouteInquiryNoAuthPortalController": "线路询价",
    "RouteInquiryPortalController": "线路询价",
    "RouteInquiryQuotePlanAdminController": "线路询价报价方案",
    "RouteInquiryQuotePlanPortalController": "线路询价报价方案",
    "StationAdminController": "站点",
    "StationPortalController": "站点",
}

BASIC_CONTROLLER_ENTITIES: dict[str, str] = {
    "AddressAdminController": "地址",
    "AddressNoAuthAdminController": "地址",
    "AddressNoAuthPortalController": "地址",
    "AddressPortalController": "地址",
    "RemoteAddressNoAuthPortalController": "地址",
    "RemoteAddressPortalController": "地址",
    "CargoBasePriceConfigAdminController": "货物基础价格配置",
    "CargoBasePriceConfigNoAuthPortalController": "货物基础价格配置",
    "CargoBasePriceConfigPortalController": "货物基础价格配置",
    "RemoteCargoBasePriceConfigPortalController": "货物基础价格配置",
    "BusinessAdminController": "业务主体",
    "BusinessPortalController": "业务主体",
    "CargoAdminController": "货物",
    "CargoCategoryAdminController": "货物类别",
    "CargoCategoryPortalController": "货物类别",
    "CargoNoAuthPortalController": "货物",
    "CargoPortalController": "货物",
    "RemoteCargoPortalController": "货物",
    "CargoExternalController": "外部货物",
    "CommonController": "基础公共数据",
    "ExpenseConfigAdminController": "费用配置",
    "ExpenseConfigPortalController": "费用配置",
    "RemoteExpenseConfigPortalController": "费用配置",
    "DivisionController": "事业部",
    "UserDivisionController": "用户事业部",
    "DriverAdminController": "司机",
    "DriverPortalController": "司机",
    "InventorySummaryAdminController": "库存汇总",
    "OutboundBoxAdminController": "出库箱",
    "RemoteOutboundBoxPortalController": "出库箱",
    "PortAdminController": "港口",
    "PortNoAuthPortalController": "港口",
    "PortPortalController": "港口",
    "RemotePortPortalController": "港口",
    "ProductArchiveAdminController": "产品档案",
    "ShipAdminController": "船舶",
    "ShipPortalController": "船舶",
    "ShipOwnerAdminController": "船东",
    "ShipOwnerPortalController": "船东",
    "SiteFeeAdminController": "站点费用",
    "SiteFeeItemAdminController": "站点费用项",
    "SiteFeeItemRangeAdminController": "站点费用项区间",
    "SiteFeePortalController": "站点费用",
    "AdministrativeRegionController": "行政区域",
    "RolePermissionController": "基础角色权限",
    "TemplateAdminController": "模板",
    "TemplatePortalController": "模板",
    "RemoteVehiclePortalController": "车辆",
    "VehicleAdminController": "车辆",
    "VehiclePortalController": "车辆",
    "WarehouseManagementAdminController": "仓库",
    "DispatchManifestPortalController": "水路舱单",
    "ShippingDispatchManifestAdminController": "水路舱单",
    "RemoteTrackPortalController": "水路运输轨迹",
    "ShippingTrackAdminController": "水路运输轨迹",
    "ShippingTrackPortalController": "水路运输轨迹",
}

HIGHWAY_CONTROLLER_ENTITIES: dict[str, str] = {
    "HighwayAttachmentAdminController": "公路附件",
    "HighwayAttachmentPortalController": "公路附件",
    "HighwayCargoAdminController": "公路货物",
    "HighwayCargoPortalController": "公路货物",
    "HighwayCarrierOrderAdminController": "公路承运订单",
    "HighwayCarrierOrderPortalController": "公路承运订单",
    "HighwayRemoteCarrierOrderPortalController": "公路承运订单",
    "HighwayDispatchOrderAdminController": "公路运输订单",
    "HighwayDispatchOrderPortalController": "公路运输订单",
    "HighwayRemoteDispatchOrderPortalController": "公路运输订单",
    "HighwayDispatchBoxPortalController": "公路派车箱",
    "HighwayRemoteDriverDispatchBoxPortalController": "公路司机派车箱",
    "HighwayInboundOrderAdminController": "公路入库单",
    "HighwayParkAppointmentAdminController": "园区预约",
    "HighwayParkAppointmentPortalController": "园区预约",
    "HighwayRecordAdminController": "公路运输记录",
    "HighwayRecordPortalController": "公路运输记录",
    "HighwayTrackAdminController": "公路运输轨迹",
    "HighwayTrackPortalController": "公路运输轨迹",
}

RAILWAY_CONTROLLER_ENTITIES: dict[str, str] = {
    "RailwayAttachmentAdminController": "铁路附件",
    "RailwayAttachmentPortalController": "铁路附件",
    "RailwayCargoAdminController": "铁路货物",
    "RailwayCargoPortalController": "铁路货物",
    "RailwayCarrierOrderAdminController": "铁路承运订单",
    "RailwayCarrierOrderPortalController": "铁路承运订单",
    "RailwayRemoteCarrierOrderPortalController": "铁路承运订单",
    "RailwayFileController": "铁路文件",
    "RailwayDailyPlanAdminController": "铁路日发运计划",
    "RailwayDailyPlanPortalController": "铁路日发运计划",
    "RailwayDispatchOrderAdminController": "铁路运输订单",
    "RailwayDispatchOrderPortalController": "铁路运输订单",
    "RailwayRemoteDispatchOrderPortalController": "铁路运输订单",
    "DispatchOrderLineAdminController": "铁路运输订单线路",
    "DispatchOrderLinePortalController": "铁路运输订单线路",
    "RailwayDispatchManifestAdminController": "铁路舱单",
    "RailwayRecordAdminController": "铁路运输记录",
    "RailwayRecordPortalController": "铁路运输记录",
    "RailwayTrackAdminController": "铁路运输轨迹",
    "RailwayTrackPortalController": "铁路运输轨迹",
}

SHIPPING_CONTROLLER_ENTITIES: dict[str, str] = {
    "ShippingAttachmentAdminController": "水路附件",
    "ShippingAttachmentPortalController": "水路附件",
    "ShippingCargoAdminController": "水路货物",
    "ShippingCargoPortalController": "水路货物",
    "ShippingCarrierOrderAdminController": "水路承运订单",
    "ShippingCarrierOrderPortalController": "水路承运订单",
    "ShippingRemoteCarrierOrderPortalController": "水路承运订单",
    "ShippingContainerAdminController": "水路集装箱",
    "ShippingDispatchOrderAdminController": "水路运输订单",
    "ShippingDispatchOrderPortalController": "水路运输订单",
    "ShippingRemoteDispatchOrderPortalController": "水路运输订单",
    "DispatchManifestPortalController": "水路舱单",
    "ShippingDispatchManifestAdminController": "水路舱单",
    "ShippingRecordAdminController": "水路运输记录",
    "ShippingRecordPortalController": "水路运输记录",
    "RemoteTrackPortalController": "水路运输轨迹",
    "ShippingTrackAdminController": "水路运输轨迹",
    "ShippingTrackPortalController": "水路运输轨迹",
}

SETTLEMENT_CONTROLLER_ENTITIES: dict[str, str] = {
    "AdvancePaymentAdminController": "预付货款",
    "AdvancePaymentPortalController": "预付货款",
    "SettlementAttachmentAdminController": "结算附件",
    "SettlementAttachmentPortalController": "结算附件",
    "BtExpenseAdminController": "班列费用",
    "CollectionAdminController": "收款",
    "CollectionPortalController": "收款",
    "SettlementExpenseConfigAdminController": "结算费用配置",
    "SettlementExpenseConfigPortalController": "结算费用配置",
    "ExpenseAdminController": "费用",
    "ExpensePortalController": "费用",
    "ModifyLogAdminController": "费用修改日志",
    "ModifyLogPortalController": "费用修改日志",
    "OperationFeeController": "操作费",
    "OwnerFundAdminController": "货主资金",
    "OwnerFundPortalController": "货主资金",
    "OwnerFundFlowAdminController": "货主资金流水",
    "PayableBillAdminController": "应付账单",
    "PayableBillPortalController": "应付账单",
    "PaymentApplyAdminController": "付款申请",
    "PaymentApplyPortalController": "付款申请",
    "PaymentApplyHistoryAdminController": "付款申请历史",
    "PaymentConfirmationAdminController": "付款确认",
    "PaymentConfirmationPortalController": "付款确认",
    "PaymentRelationAdminController": "付款关联",
    "PaymentRelationPortalController": "付款关联",
    "PaymentVerificationAdminController": "付款核销",
    "PaymentVerificationPortalController": "付款核销",
    "PrepaymentAdminController": "预付款",
    "PrepaymentPortalController": "预付款",
    "ReceiptConfirmationAdminController": "收款确认",
    "ReceiptConfirmationPortalController": "收款确认",
    "ReceiptVerificationAdminController": "收款核销",
    "ReceiptVerificationPortalController": "收款核销",
    "ReceivableBillAdminController": "应收账单",
    "ReceivableBillPortalController": "应收账单",
    "SalesInvoiceAdminController": "销项发票",
    "SalesInvoicePortalController": "销项发票",
}

DECLARATION_CONTROLLER_ENTITIES: dict[str, str] = {
    "AttachmentAdminController": "申报附件",
    "AttachmentPortalController": "申报附件",
    "OrderCargoAttributeAdminController": "订单货物申报要素",
    "OrderCargoAttributePortalController": "订单货物申报要素",
    "BasicInformationAdminController": "申报基础资料",
    "BasicInformationPortalController": "申报基础资料",
    "OrderCargoAdminController": "申报订单货物",
    "OrderCargoPortalController": "申报订单货物",
    "CommodityAdminController": "申报商品",
    "CommodityPortalController": "申报商品",
    "CommodityBasicDataAdminController": "商品基础资料",
    "CommodityBasicDataPortalController": "商品基础资料",
    "CommodityCatalogAdminController": "商品目录",
    "OrderContainerAdminController": "申报订单集装箱",
    "OrderContainerPortalController": "申报订单集装箱",
    "OrderDeclareAdminController": "报关单",
    "OrderDeclarePortalController": "报关单",
    "OrderDocumentAdminController": "随附单证",
    "OrderDocumentPortalController": "随附单证",
    "QuarantineEnterpriseAdminController": "检验检疫企业",
    "QuarantineEnterprisePortalController": "检验检疫企业",
    "EntrustAdminController": "报关委托",
    "EntrustPortalController": "报关委托",
    "OrderAdminController": "申报订单",
    "OrderPortalController": "申报订单",
    "OriginAdminController": "原产地",
    "OriginPortalController": "原产地",
    "OrderQuarantineAdminController": "检验检疫信息",
    "OrderQuarantinePortalController": "检验检疫信息",
    "DeclarationRolePermissionController": "申报角色权限",
    "OrderTransportAdminController": "申报运输信息",
    "OrderTransportPortalController": "申报运输信息",
}

OPERATION_CONTROLLER_ENTITIES: dict[str, str] = {
    "AppointmentAdminController": "作业预约",
    "AppointmentPortalController": "作业预约",
    "AppointmentVehicleController": "预约车辆",
    "OperationAttachmentAdminController": "作业附件",
    "OperationAttachmentPortalController": "作业附件",
    "OperationPortAdminController": "作业港口",
    "OperationPortPortalController": "作业港口",
    "ContainerPortalController": "作业集装箱",
    "OperationContainerAdminController": "作业集装箱",
    "OperationEntrustedAdminController": "作业委托需求",
    "OperationEntrustedPortalController": "作业委托需求",
    "OperationEntrustedOrderAdminController": "作业委托订单",
    "OperationEntrustedOrderPortalController": "作业委托订单",
    "EntrustedBusinessTypeController": "委托业务类型",
    "OperationEntrustedQuoteAdminController": "委托需求报价",
    "OperationEntrustedQuotePortalController": "委托需求报价",
    "EntrustedQuoteInfoAdminController": "委托报价信息",
    "EntrustedQuoteInfoPortalController": "委托报价信息",
    "GeneralCargoAdminController": "普货",
    "GeneralCargoPortalController": "普货",
    "PickUpAppointmentController": "提货预约",
    "OperationRolePermissionController": "作业角色权限",
    "WorkNodeAdminController": "作业节点",
    "WorkNodePortalController": "作业节点",
}

MESSAGE_CONTROLLER_ENTITIES: dict[str, str] = {
    "EmailSenderController": "邮件发送方",
    "EmailSignController": "邮件签名",
    "GroupRobotApi": "群机器人",
    "GroupRobotController": "群机器人",
    "MessageApi": "内部消息",
    "MessageController": "手工消息",
    "MessageFileController": "消息文件",
    "MessageRolePermissionController": "消息角色权限",
    "MessageTemplateApi": "消息模板",
    "MessageTemplateController": "消息模板",
    "MessageTemplateGroupController": "消息模板分组",
    "SmsSenderController": "短信发送方",
}

EXTERNAL_INTERFACE_CONTROLLER_ENTITIES: dict[str, str] = {
    "ExternalInterfaceRolePermissionController": "用户菜单权限",
    "FeeFeeBillController": "港口作业费用账单",
    "FeeInfoController": "港口作业费用信息",
    "RailwayTransportController": "智运铁路运输位置与轨迹",
    "SmsController": "短信",
}

DECLARATION_INTERFACE_CONTROLLER_ENTITIES: dict[str, str] = {
    "DeclarationInterfaceRolePermissionController": "申报集成用户菜单权限",
}

WEB_ADMIN_CONTROLLER_ENTITIES: dict[str, str] = {
    "AccountOverviewController": "账户概览",
    "BtAttachmentController": "班列附件",
    "BtDailyPlanController": "日计划",
    "BtDeparturePlanChangeRecordController": "发车计划变更记录",
    "BtDeparturePlanController": "发车计划",
    "BtDeparturePlanDailyPlanController": "发车计划日计划",
    "BtDeparturePlanStationController": "发车计划站点",
    "BtRouteController": "班列线路",
    "BtTrainOperationExceptionRecordController": "列车运营异常记录",
    "BtTrainOperationLogController": "列车运营日志",
    "BtTrainOperationMonitorController": "列车运营监控",
    "BtTrainOperationTrackingController": "列车运营跟踪",
    "BtTrainPlanListController": "列车计划",
    "BtWaybillController": "班列运单",
    "DriverController": "司机",
    "MonthlyEntrustedController": "月度委托",
    "MonthlyEntrustedSupplementController": "月度委托补充单",
    "ShipperWorkbenchStatisticsController": "托运人工作台统计",
}

JOB_CLIENT_CONTROLLER_ENTITIES: dict[str, str] = {
    "JobLogMessageController": "任务日志",
    "WarningRuleJobApiController": "预警规则任务",
    "JobController": "定时任务",
    "JobTaskController": "任务实例",
    "JobTaskBatchController": "任务批次",
}

TRACE_CONTROLLER_ENTITIES: dict[str, str] = {
    "TraceRolePermissionController": "轨迹角色权限",
    "MapTrackAdminController": "运输轨迹",
    "MapTrackPortalController": "运输轨迹",
}


@dataclass(frozen=True, slots=True)
class JavaMethod:
    name: str
    route: str
    body: str
    mapped: bool = False


@dataclass(slots=True)
class JavaClass:
    name: str
    source_file: str
    extends: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    methods: dict[str, JavaMethod] = field(default_factory=dict)
    method_list: list[JavaMethod] = field(default_factory=list)
    dao_name: str = ""
    model_name: str = ""


@dataclass(frozen=True, slots=True)
class InterfaceTableEffect:
    table_name: str
    effect_type: str
    response_contribution: str
    source_file: str
    source_class: str
    source_method: str
    call_path: tuple[str, ...]
    evidence_type: str
    confidence: int
    sql_statement_id: str = ""


@dataclass(frozen=True, slots=True)
class InterfaceSourceAnalysis:
    controller_found: bool
    controller_method: str
    crud_type: str
    business_entity: str
    business_action: str
    business_scenario: str
    aliases: tuple[str, ...]
    positive_examples: tuple[str, ...]
    effects: tuple[InterfaceTableEffect, ...]


class OrderApiSourceAnalyzer:
    """Conservative Java call-graph scanner for c12-mtp order-api interfaces."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        module_name: str = "order",
        sql_id_class: str = "OrderSqlId",
        sql_id_classes: tuple[str, ...] = (),
        table_prefixes: tuple[str, ...] = ("cs_",),
        controller_entities: dict[str, str] | None = None,
        additional_modules: tuple[tuple[str, str], ...] = (),
        java_relative_roots: tuple[str, ...] = (),
        sql_relative_roots: tuple[str, ...] = (),
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.module_name = module_name
        self.controller_entities = controller_entities or ORDER_CONTROLLER_ENTITIES
        self.sql_id_class = sql_id_class
        self.table_prefixes = table_prefixes
        self.source_modules = ((module_name, sql_id_class), *additional_modules)
        all_sql_id_classes = tuple(
            dict.fromkeys(
                (
                    *(item[1] for item in self.source_modules),
                    *sql_id_classes,
                )
            )
        )
        self.sql_id_re = re.compile(
            rf"\b({'|'.join(re.escape(item) for item in all_sql_id_classes)})\.(\w+)"
        )
        self.java_roots = (
            tuple(self.workspace_root / item for item in java_relative_roots)
            if java_relative_roots
            else tuple(
                self.workspace_root
                / (
                    f"backend/c12-mtp/c12-mtp-{source_module}-service/"
                    f"c12-mtp-{source_module}-biz/src/main/java"
                )
                for source_module, _sql_class in self.source_modules
            )
        )
        self.sql_roots = (
            tuple(self.workspace_root / item for item in sql_relative_roots)
            if sql_relative_roots
            else tuple(
                self.workspace_root
                / (
                    f"backend/c12-mtp/c12-mtp-{source_module}-service/"
                    f"c12-mtp-{source_module}-biz/src/main/resources/sql-ext"
                )
                for source_module, _sql_class in self.source_modules
            )
        )
        self.java_root = self.java_roots[0]
        self.sql_root = self.sql_roots[0]
        if not self.java_root.is_dir():
            raise ValueError(f"{module_name}-api Java 源码目录不存在: {self.java_root}")
        self.sql_id_filenames = {
            f"{source_sql_id_class}.java" for source_sql_id_class in all_sql_id_classes
        }
        self.classes: dict[str, JavaClass] = {}
        self.table_by_model: dict[str, str] = {}
        self.sql_id_by_constant: dict[str, str] = {}
        self.sql_effects: dict[str, tuple[tuple[str, str], ...]] = {}
        self._load_sources()

    def analyze(
        self,
        *,
        controller_name: str,
        path: str,
        method: str,
        interface_name: str,
        existing_crud_type: str = "unknown",
        operation_id: str = "",
    ) -> InterfaceSourceAnalysis:
        controller = self.classes.get(controller_name)
        # 部分 inner OpenAPI 文档会把接口类 `FooApi` 记录成
        # `FooApiController`。优先保留精确匹配，仅在缺失时回退到源码类名。
        if controller is None and controller_name.endswith("Controller"):
            controller = self.classes.get(controller_name.removesuffix("Controller"))
        controller_method = self._controller_method(controller, path, operation_id)
        effects: list[InterfaceTableEffect] = []
        if controller is not None and controller_method is not None:
            effects = self._trace(
                controller.name,
                controller_method.name,
                call_path=(),
                visited=frozenset(),
                depth=0,
                method_override=controller_method,
            )
        crud_type = existing_crud_type if existing_crud_type != "unknown" else ""
        if not crud_type:
            crud_type = self._crud_from_effects(
                interface_name,
                method,
                effects,
                controller_method.name if controller_method else "",
            )
        entity = self.controller_entities.get(controller_name)
        if not entity and controller is not None:
            entity = self.controller_entities.get(controller.name)
        if not entity:
            entity = self._fallback_entity(interface_name)
        scope = "门户端" if "/portal/" in path else "运营端" if "/admin/" in path else "内部"
        scenario = f"{scope}{interface_name}"
        aliases = self._semantic_aliases(interface_name, entity, scope, crud_type)
        examples = self._unique((interface_name, f"请{interface_name}"))
        return InterfaceSourceAnalysis(
            controller_found=controller is not None,
            controller_method=controller_method.name if controller_method else "",
            crud_type=crud_type,
            business_entity=entity,
            business_action=interface_name,
            business_scenario=scenario,
            aliases=aliases,
            positive_examples=examples,
            effects=tuple(self._deduplicate_effects(effects)),
        )

    def _load_sources(self) -> None:
        java_sources: list[tuple[Path, str, str]] = []
        for java_root in self.java_roots:
            for path in sorted(java_root.rglob("*.java")):
                raw = path.read_text(encoding="utf-8", errors="ignore")
                clean = _COMMENT_RE.sub(lambda match: " " * len(match.group(0)), raw)
                java_sources.append((path, raw, clean))
                class_match = _CLASS_RE.search(clean)
                table_match = _TABLE_RE.search(clean)
                if class_match and table_match:
                    self.table_by_model[class_match.group(1)] = table_match.group(1)
                if path.name in self.sql_id_filenames:
                    self.sql_id_by_constant.update(
                        {
                            f"{path.stem}.{constant}": sql_id
                            for constant, sql_id in _SQL_CONSTANT_RE.findall(clean)
                        }
                    )
        for path, _raw, clean in java_sources:
            parsed = self._parse_class(path, clean)
            if parsed is not None:
                self.classes[parsed.name] = parsed
        for sql_root in self.sql_roots:
            for sql_path in sorted(sql_root.rglob("*.sql")):
                sql = _COMMENT_RE.sub(
                    " ", sql_path.read_text(encoding="utf-8", errors="ignore")
                )
                statement = sql.lstrip().split(None, 1)[0].lower() if sql.strip() else ""
                default_effect = {
                    "select": "select",
                    "insert": "insert",
                    "update": "update",
                    "delete": "delete",
                }.get(statement, "select")
                found: list[tuple[str, str]] = []
                for table in _SQL_TABLE_RE.findall(sql):
                    normalized = table.split(".")[-1].lower()
                    if normalized.startswith(self.table_prefixes):
                        found.append((normalized, default_effect))
                self.sql_effects[sql_path.stem] = tuple(dict.fromkeys(found))

    def _parse_class(self, path: Path, clean: str) -> JavaClass | None:
        class_match = _CLASS_RE.search(clean)
        if class_match is None:
            return None
        service_match = _SERVICE_MODEL_RE.search(clean)
        dao_match = _DAO_MODEL_RE.search(clean) or _JPA_DAO_MODEL_RE.search(clean)
        parsed = JavaClass(
            name=class_match.group(1),
            extends=class_match.group(2) or "",
            source_file=str(path.relative_to(self.workspace_root)),
            fields={name: type_name.split(".")[-1] for type_name, name in _FIELD_RE.findall(clean)},
            dao_name=service_match.group(1) if service_match else "",
            model_name=(
                service_match.group(2) if service_match else dao_match.group(1) if dao_match else ""
            ),
        )
        previous_end = class_match.end()
        for method_match in _METHOD_RE.finditer(clean):
            brace_at = method_match.end() - 1
            end = self._matching_brace(clean, brace_at)
            if end < 0:
                continue
            prefix = clean[max(previous_end, method_match.start() - 800) : method_match.start()]
            mappings = list(_MAPPING_RE.finditer(prefix))
            route = (mappings[-1].group(1) or "") if mappings else ""
            method_name = method_match.group(1)
            parsed.methods.setdefault(
                method_name,
                JavaMethod(
                    name=method_name,
                    route=route,
                    body=clean[brace_at + 1 : end],
                    mapped=bool(mappings),
                ),
            )
            parsed.method_list.append(
                JavaMethod(
                    name=method_name,
                    route=route,
                    body=clean[brace_at + 1 : end],
                    mapped=bool(mappings),
                )
            )
            previous_end = end + 1
        return parsed

    @staticmethod
    def _matching_brace(text: str, start: int) -> int:
        depth = 0
        quote = ""
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
                continue
            if char in {'"', "'"}:
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
        return -1

    def _controller_method(
        self,
        controller: JavaClass | None,
        path: str,
        operation_id: str,
    ) -> JavaMethod | None:
        if controller is None:
            return None
        if operation_id and operation_id in controller.methods:
            return controller.methods[operation_id]
        route_matches = [
            item
            for item in controller.method_list
            if item.route and path.endswith(self._normalize_route(item.route))
        ]
        if len(route_matches) == 1:
            return route_matches[0]
        root_mapping_matches = [
            item for item in controller.method_list if item.mapped and not item.route
        ]
        if len(root_mapping_matches) == 1:
            return root_mapping_matches[0]
        action = next(
            (part for part in reversed(path.split("/")) if part and not part.startswith("{")),
            "",
        )
        action_names = {
            action.lower(),
            action.lower().replace("temple", "template"),
        }
        action_matches = [
            item
            for item in controller.method_list
            if item.name.lower() in action_names
            or any(item.name.lower().endswith(name) for name in action_names)
        ]
        if len(action_matches) == 1:
            return action_matches[0]
        return None

    def _trace(
        self,
        class_name: str,
        method_name: str,
        *,
        call_path: tuple[str, ...],
        visited: frozenset[tuple[str, str]],
        depth: int,
        method_override: JavaMethod | None = None,
    ) -> list[InterfaceTableEffect]:
        if depth > 8 or (class_name, method_name) in visited:
            return []
        if method_override is not None:
            source_class = self.classes.get(class_name)
            source_method = method_override
        else:
            source_class, source_method = self._find_method(class_name, method_name)
        if source_class is None or source_method is None:
            table = self._primary_table(class_name)
            effect = self._effect_from_method(method_name)
            return self._fallback_effects(
                class_name,
                method_name,
                table,
                effect,
                call_path,
            )
        current_path = (*call_path, f"{source_class.name}.{source_method.name}")
        next_visited = visited | {(class_name, method_name)}
        effects = self._sql_effects(source_class, source_method, current_path)
        own_table = self._primary_table(source_class.name)
        for base_method in _BASE_CALL_RE.findall(source_method.body):
            effect = self._effect_from_method(base_method)
            if own_table and effect:
                effects.append(
                    self._effect(
                        table=own_table,
                        effect=effect,
                        source_class=source_class,
                        source_method=source_method.name,
                        call_path=current_path,
                        confidence=88,
                    )
                )
        for local_method in _BARE_CALL_RE.findall(source_method.body):
            if local_method == source_method.name or local_method not in source_class.methods:
                continue
            effects.extend(
                self._trace(
                    source_class.name,
                    local_method,
                    call_path=current_path,
                    visited=next_visited,
                    depth=depth + 1,
                )
            )
        for receiver, called_method in _MEMBER_CALL_RE.findall(source_method.body):
            if receiver in {"this", "super"}:
                target_name = source_class.name
            elif receiver == "dao":
                target_name = self._dao_type(source_class.name) or self._field_type(
                    source_class.name, receiver
                )
                if target_name and target_name in self.classes:
                    nested = self._trace(
                        target_name,
                        called_method,
                        call_path=current_path,
                        visited=next_visited,
                        depth=depth + 1,
                    )
                    if nested:
                        effects.extend(nested)
                        continue
                effect = self._effect_from_method(called_method)
                if own_table and effect:
                    effects.append(
                        self._effect(
                            table=own_table,
                            effect=effect,
                            source_class=source_class,
                            source_method=source_method.name,
                            call_path=current_path,
                            confidence=92,
                        )
                    )
                continue
            else:
                target_name = self._field_type(source_class.name, receiver)
            if not target_name or target_name not in self.classes:
                continue
            nested = self._trace(
                target_name,
                called_method,
                call_path=current_path,
                visited=next_visited,
                depth=depth + 1,
            )
            effects.extend(nested)
        if not effects and own_table:
            effect = self._effect_from_method(method_name)
            if effect:
                effects.extend(
                    self._fallback_effects(
                        source_class.name,
                        source_method.name,
                        own_table,
                        effect,
                        call_path,
                    )
                )
        return effects

    def _sql_effects(
        self,
        source_class: JavaClass,
        method: JavaMethod,
        call_path: tuple[str, ...],
    ) -> list[InterfaceTableEffect]:
        effects: list[InterfaceTableEffect] = []
        for sql_class, constant in self.sql_id_re.findall(method.body):
            sql_id = self.sql_id_by_constant.get(f"{sql_class}.{constant}", "")
            for table, effect in self.sql_effects.get(sql_id, ()):
                effects.append(
                    self._effect(
                        table=table,
                        effect=effect,
                        source_class=source_class,
                        source_method=method.name,
                        call_path=call_path,
                        confidence=98,
                        sql_statement_id=sql_id,
                    )
                )
        for sql_id in _SQL_LITERAL_RE.findall(method.body):
            for table, effect in self.sql_effects.get(sql_id, ()):
                effects.append(
                    self._effect(
                        table=table,
                        effect=effect,
                        source_class=source_class,
                        source_method=method.name,
                        call_path=call_path,
                        confidence=98,
                        sql_statement_id=sql_id,
                    )
                )
        return effects

    def _find_method(
        self,
        class_name: str,
        method_name: str,
    ) -> tuple[JavaClass | None, JavaMethod | None]:
        current = self.classes.get(class_name)
        seen: set[str] = set()
        while current is not None and current.name not in seen:
            seen.add(current.name)
            if method := current.methods.get(method_name):
                return current, method
            current = self.classes.get(current.extends)
        return None, None

    def _field_type(self, class_name: str, field_name: str) -> str:
        current = self.classes.get(class_name)
        seen: set[str] = set()
        while current is not None and current.name not in seen:
            seen.add(current.name)
            if field_name in current.fields:
                return current.fields[field_name]
            current = self.classes.get(current.extends)
        return ""

    def _primary_table(self, class_name: str) -> str:
        current = self.classes.get(class_name)
        seen: set[str] = set()
        while current is not None and current.name not in seen:
            seen.add(current.name)
            if table := self.table_by_model.get(current.model_name):
                return table
            current = self.classes.get(current.extends)
        return ""

    def _dao_type(self, class_name: str) -> str:
        current = self.classes.get(class_name)
        seen: set[str] = set()
        while current is not None and current.name not in seen:
            seen.add(current.name)
            if current.dao_name:
                return current.dao_name
            current = self.classes.get(current.extends)
        return ""

    @staticmethod
    def _normalize_route(route: str) -> str:
        return re.sub(r"\{([^}:]+):[^}]+\}", r"{\1}", route)

    def _fallback_effects(
        self,
        class_name: str,
        method_name: str,
        table: str,
        effect: str,
        call_path: tuple[str, ...],
    ) -> list[InterfaceTableEffect]:
        source_class = self.classes.get(class_name)
        if source_class is None or not table or not effect:
            return []
        return [
            self._effect(
                table=table,
                effect=effect,
                source_class=source_class,
                source_method=method_name,
                call_path=(*call_path, f"{class_name}.{method_name}"),
                confidence=76,
                evidence_type="convention",
            )
        ]

    @staticmethod
    def _effect_from_method(method_name: str) -> str:
        normalized = method_name.lower()
        if any(word in normalized for word in ("delete", "remove")):
            return "delete"
        if "saveorupdate" in normalized or "upsert" in normalized:
            return "upsert"
        if any(word in normalized for word in ("batchinsert", "insert", "create", "generate")):
            return "insert"
        if any(
            word in normalized
            for word in (
                "update",
                "edit",
                "change",
                "approve",
                "reject",
                "withdraw",
                "cancel",
                "confirm",
                "sign",
                "distribute",
            )
        ):
            return "update"
        if normalized == "save" or normalized.startswith("save"):
            return "upsert"
        if any(
            word in normalized
            for word in (
                "find",
                "get",
                "page",
                "list",
                "query",
                "count",
                "exists",
                "check",
                "download",
                "statistics",
                "export",
            )
        ):
            return "select"
        return ""

    def _effect(
        self,
        *,
        table: str,
        effect: str,
        source_class: JavaClass,
        source_method: str,
        call_path: tuple[str, ...],
        confidence: int,
        evidence_type: str = "source_scan",
        sql_statement_id: str = "",
    ) -> InterfaceTableEffect:
        return InterfaceTableEffect(
            table_name=table,
            effect_type=effect,
            response_contribution="returned" if effect == "select" else "none",
            source_file=source_class.source_file,
            source_class=source_class.name,
            source_method=f"{source_class.name}.{source_method}",
            call_path=(*call_path, f"{table}:{effect}"),
            evidence_type=evidence_type,
            confidence=confidence,
            sql_statement_id=sql_statement_id,
        )

    def _crud_from_effects(
        self,
        name: str,
        method: str,
        effects: list[InterfaceTableEffect],
        source_method: str = "",
    ) -> str:
        normalized = name.strip()
        if not effects and source_method:
            source_effect = self._effect_from_method(source_method)
            source_crud = {
                "select": "read",
                "insert": "create",
                "update": "update",
                "delete": "delete",
                "upsert": "update",
            }.get(source_effect)
            if source_crud:
                return source_crud
        if re.match(r"^(删除|批量删除|清除|移除)", normalized):
            return "delete"
        if re.match(
            r"^(查询|分页查询|分页选择|选择|获取|统计|下载|导出|预览|校验|检查|搜索|列出|判断|按.+(?:查询|获取))",
            normalized,
        ):
            return "read"
        if re.match(r"^(新增|创建|生成|上传|导入|发起|发送|批量发送)", normalized):
            return "create"
        if re.match(
            r"^(更新|修改|保存|编辑|提交|确认|审核|审批|接受|拒绝|驳回|启用|停用|批量启用|批量停用|同步|处理|关联|指定|变更|撤回|作废|取消|撤销|注销|签署|分配|触发|执行|启动|暂停|停止|重试|恢复|批量发起|批量调度|重新调度|调度|装货|卸货)",
            normalized,
        ):
            return "update"
        types = {item.effect_type for item in effects}
        if types and types <= {"select"}:
            return "read"
        if types and types <= {"delete"}:
            return "delete"
        if types and types <= {"insert"}:
            return "create"
        if types - {"select"}:
            return "update"
        if method.upper() in {"GET", "HEAD", "OPTIONS"}:
            return "read"
        if method.upper() == "DELETE":
            return "delete"
        if method.upper() in {"PUT", "PATCH"}:
            return "update"
        return "unknown"

    @staticmethod
    def _deduplicate_effects(
        effects: list[InterfaceTableEffect],
    ) -> list[InterfaceTableEffect]:
        selected: dict[tuple[str, str], InterfaceTableEffect] = {}
        for effect in effects:
            key = (effect.table_name, effect.effect_type)
            existing = selected.get(key)
            if existing is None or effect.confidence > existing.confidence:
                selected[key] = effect
        return sorted(selected.values(), key=lambda item: (item.table_name, item.effect_type))

    @staticmethod
    def _fallback_entity(interface_name: str) -> str:
        entity = re.sub(
            r"^(分页查询|分页选择|批量查询|查询|选择|按.+?查询|获取|新增|创建|生成|上传|导入|发起|发送|批量发送|"
            r"更新|修改|保存|编辑|提交|确认|审核|审批|批量发起|批量调度|重新调度|调度|装货|卸货|删除|批量删除)",
            "",
            interface_name,
        ).strip()
        return entity or interface_name

    @staticmethod
    def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))

    def _semantic_aliases(
        self,
        interface_name: str,
        entity: str,
        scope: str,
        crud_type: str,
    ) -> tuple[str, ...]:
        values = [interface_name, f"{scope}{interface_name}"]
        if crud_type == "read" and interface_name.startswith("分页查询"):
            values.extend((f"分页查询{entity}", f"{entity}列表"))
        elif crud_type == "read" and (
            interface_name.startswith("按 ID 查询") or "详情" in interface_name
        ):
            values.extend((f"按 ID 查询{entity}", f"查看{entity}详情", f"{entity}详情"))
        elif crud_type == "create":
            values.extend((f"新增{entity}", f"创建{entity}"))
        elif crud_type == "update" and interface_name.startswith(("保存", "更新", "修改", "编辑")):
            values.extend((f"保存{entity}", f"更新{entity}", f"修改{entity}"))
        elif crud_type == "delete":
            values.extend((f"删除{entity}", f"批量删除{entity}"))
        return self._unique(tuple(values))


class LineApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Conservative Java call-graph scanner for c12-mtp line-api interfaces."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="line",
            sql_id_class="LineSqlId",
            controller_entities=LINE_CONTROLLER_ENTITIES,
        )


class BasicApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Conservative Java call-graph scanner for c12-mtp basic-api interfaces."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="basic",
            sql_id_class="BasicSqlId",
            controller_entities=BASIC_CONTROLLER_ENTITIES,
            additional_modules=(("shipping", "ShippingSqlId"),),
        )


class HighwayApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Conservative Java call-graph scanner for c12-mtp highway-api interfaces."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="highway",
            sql_id_class="HighwaySqlId",
            controller_entities=HIGHWAY_CONTROLLER_ENTITIES,
        )


class RailwayApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Conservative Java call-graph scanner for c12-mtp railway-api interfaces."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="railway",
            sql_id_class="RailwaySqlId",
            controller_entities=RAILWAY_CONTROLLER_ENTITIES,
        )


class ShippingApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Conservative Java call-graph scanner for c12-mtp shipping-api interfaces."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="shipping",
            sql_id_class="ShippingSqlId",
            controller_entities=SHIPPING_CONTROLLER_ENTITIES,
        )


class SettlementApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Conservative Java call-graph scanner for c12-mtp settlement-api interfaces."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="settlement",
            sql_id_class="SettlementSqlId",
            controller_entities=SETTLEMENT_CONTROLLER_ENTITIES,
        )


class DeclarationApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Conservative Java call-graph scanner for c12-mtp declaration-api interfaces."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="declaration",
            sql_id_class="DeclarationSqlId",
            controller_entities=DECLARATION_CONTROLLER_ENTITIES,
        )


class OperationApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Conservative Java call-graph scanner for c12-mtp operation-api interfaces."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="operation",
            sql_id_class="EntrustedSqlId",
            sql_id_classes=(
                "EntrustedOrderSqlId",
                "GeneralCargoSqlId",
                "ContainerSqlId",
                "AppointmentVehicleSqlId",
                "AppointmentSqlId",
                "FeeSqlId",
                "WorkNodeSqlId",
                "PickUpAppointmentSqlId",
            ),
            controller_entities=OPERATION_CONTROLLER_ENTITIES,
        )


class MessageApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Conservative Java call-graph scanner for c12-mtp message-api interfaces."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="message",
            sql_id_class="MessageSqlId",
            controller_entities=MESSAGE_CONTROLLER_ENTITIES,
        )

    def _crud_from_effects(
        self,
        name: str,
        method: str,
        effects: list[InterfaceTableEffect],
        source_method: str = "",
    ) -> str:
        if source_method == "appointReceiverRole":
            return "read"
        return super()._crud_from_effects(name, method, effects, source_method)


class ExternalInterfaceApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Source scanner for c12-mtp external-interface-api routes."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="external-interface",
            sql_id_class="ExternalInterfaceSqlId",
            controller_entities=EXTERNAL_INTERFACE_CONTROLLER_ENTITIES,
        )

    def analyze(
        self,
        *,
        controller_name: str,
        path: str,
        method: str,
        interface_name: str,
        existing_crud_type: str = "unknown",
        operation_id: str = "",
    ) -> InterfaceSourceAnalysis:
        analysis = super().analyze(
            controller_name=controller_name,
            path=path,
            method=method,
            interface_name=interface_name,
            existing_crud_type=existing_crud_type,
            operation_id=operation_id,
        )
        canonical_action = {
            "/zhiyun/railwayTransLocation": "查询铁路运输位置",
        }.get(path)
        if not canonical_action:
            return analysis
        return replace(
            analysis,
            business_action=canonical_action,
            business_scenario=f"内部{canonical_action}",
            aliases=self._semantic_aliases(
                canonical_action,
                analysis.business_entity,
                "内部",
                analysis.crud_type,
            ),
            positive_examples=self._unique(
                (canonical_action, f"请{canonical_action}")
            ),
        )


class DeclarationInterfaceApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Source scanner for c12-mtp declaration-interface-api routes."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="declaration-interface",
            sql_id_class="SqlId",
            controller_entities=DECLARATION_INTERFACE_CONTROLLER_ENTITIES,
        )


class WebAdminApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Source scanner for the flat c12-mtp-web-service /admin routes."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="web",
            sql_id_class="BtTransportSqlId",
            controller_entities=WEB_ADMIN_CONTROLLER_ENTITIES,
            java_relative_roots=(
                "backend/c12-mtp/c12-mtp-web-service/src/main/java",
            ),
            sql_relative_roots=(
                "backend/c12-mtp/c12-mtp-web-service/src/main/resources/sql-ext",
            ),
        )


class JobClientApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Conservative Java call-graph scanner for c12-mtp job-client-api interfaces."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="job-client",
            sql_id_class="JobClientAdminSqlId",
            table_prefixes=("xxl_job_",),
            controller_entities=JOB_CLIENT_CONTROLLER_ENTITIES,
        )


class TraceApiSourceAnalyzer(OrderApiSourceAnalyzer):
    """Conservative Java call-graph scanner for c12-mtp trace-api interfaces."""

    def __init__(self, workspace_root: Path) -> None:
        super().__init__(
            workspace_root,
            module_name="trace",
            sql_id_class="TraceSqlId",
            controller_entities=TRACE_CONTROLLER_ENTITIES,
        )
