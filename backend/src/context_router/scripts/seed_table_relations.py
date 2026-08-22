"""Seed the table relations the explorer page renders.

v1 has no build pipeline: nothing discovers relations yet. This script writes one
published generation by hand, and every row in it is a real measurement taken
against the 攀枝花 UAT ``c12_mtp_db``, not an invention. Running it again replaces
the single generation for the workspace, so it is safe to repeat. ``environment``
records which environment supplied the snapshot; it does not create parallel graphs.

Real data is the point rather than a nicety. The whole reason a relation carries
two verdicts is that the code and the rows can disagree, and a disagreement is
almost impossible to fabricate convincingly: the interesting cases here are
columns the code is free to fill many times over that happen to hold exactly one
row per key, a column declared beside the one that is actually used and never
written at all, and a whole domain that has never been switched on. Each of those
was measured, and the counts are quoted next to the rows they came from.

Writing down where each code verdict came from cost four of the six
disagreements, and it was worth exactly that. All four had failed the same way: a
``batchInsert`` had been read as many children per parent when the loop around it
was minting a fresh parent key every pass and hanging one child on each. The
batch was wide, not deep. One of them had been justified as batch writing in a
path that contains no batch call at all. The verdicts now have to be conclusions
their own sites support, which is what ``check_sites`` refuses to let go.

The counts also carry a finding neither verdict reports. ``cs_dsly_highway_cargo``
uses 51 distinct ``cargo_id`` values against 48 surviving rows in
``cs_dsly_basic_cargo``, and 27 of those values resolve to no row at all. Both
dimensions call that relation a healthy one-to-many, because neither of them ever
asks whether a key points at anything.

    docker compose exec backend python -m context_router.scripts.seed_table_relations
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg

from context_router.config import Settings
from context_router.repositories.table_relation_repository import (
    InMemoryTableRelationRepository,
    TableRelationCodeSiteRecord,
    TableRelationEdgeRecord,
    TableRelationGenerationRecord,
    TableRelationTableRecord,
    TableRelationUpdateSiteRecord,
    TableRelationWriteSiteRecord,
)
from context_router.schemas.table_relations import (
    TableRelationKeyKind,
    TableRelationMeasurement,
)
from context_router.services.table_relation_query import (
    TableRelationCounters,
    project_table_counters,
)
from context_router.services.table_relation_rules import (
    check_counts,
    check_sites,
    check_update_site,
    check_verdict,
    check_write_site,
    db_verdict_from_counts,
    is_common_column,
    is_dead_column,
)


@dataclass(frozen=True, slots=True)
class SeedMeasurement:
    """The counts one relation was measured at, straight off the UAT probes.

    ``key_kind`` covers both ends. Every pair measured here matched on both sides
    -- ``*_no`` keys are all ``varchar`` and ``*_id`` keys are all ``bigint`` -- so
    there is no mismatch in this data to show. The check for one exists anyway,
    because the day a numeric key points at a string one the join stops working
    and nothing else on the page would say why.
    """

    key_kind: TableRelationKeyKind
    child_table_rows: int
    child_rows_with_value: int
    child_distinct_keys: int
    parent_rows_with_value: int
    parent_distinct_keys: int
    orphan_keys: int = 0


@dataclass(frozen=True, slots=True)
class SeedSite:
    """One place in the 攀枝花 source a code verdict was read off.

    ``kind`` is the only judgement recorded. What role the site plays and what
    multiplicity it argues for follow from it, and are computed on read so the
    three can never be stored disagreeing with each other.

    ``file`` is relative to the workspace root and there is no line number, so
    the pair of ``file`` and ``method`` plus ``snippet`` is what a reader
    searches for. That is deliberate: a line number would keep looking exact
    after an edit moved the code.
    """

    kind: str
    file: str
    method: str
    snippet: str


@dataclass(frozen=True, slots=True)
class SeedWrite:
    """One persist call against a table, independent of any relation.

    ``table`` is the table being written, not a column. ``kind`` names the
    persistence call. The same method may also appear as a relation code site;
    that is not a duplicate, because those sites answer how a parent key is
    assigned and this answers which call writes the row.
    """

    table: str
    kind: str
    file: str
    method: str
    snippet: str


@dataclass(frozen=True, slots=True)
class SeedUpdate:
    """One update call against a table, independent of any relation or insert.

    Same grain as ``SeedWrite``: the table being updated, not a column. A method
    that inserts and later updates is recorded on both lists, once each.
    """

    table: str
    kind: str
    file: str
    method: str
    snippet: str


@dataclass(frozen=True, slots=True)
class SeedEdge:
    """One relation declared the way a human reads it: parent then child.

    ``parent`` owns the key being pointed at, ``child`` owns the referencing
    column. The canonical left/right pair the table stores is derived from these
    two, so the seed never has to know which endpoint sorts first.

    Only the code dimension is declared. The data verdict is read off ``measured``
    instead, because the counts are where it comes from and a hand-written verdict
    beside its own numbers is just an opportunity to contradict them.

    ``sites`` is what the code verdict rests on, and declaring it is what makes
    that verdict answerable to something. ``reason`` survives as the one-line
    summary of what the sites add up to.
    """

    parent: str
    child: str
    code_cardinality: str
    code_evidence: str
    measured: SeedMeasurement
    reason: str
    sites: tuple[SeedSite, ...] = ()
    cross_database: bool = False

    @property
    def db_verdict(self) -> tuple[str, str]:
        return db_verdict_from_counts(_measurement(self.measured))


MTP = "c12_mtp_db.uat_mtp"
PORTAL = "c12_portal_db.uat_portal"

# Where the 攀枝花 sources sit relative to that workspace's root. Relative because
# an absolute path would be this machine's answer to a question about a repository.
_HIGHWAY = (
    "backend/c12-mtp/c12-mtp-highway-service/c12-mtp-highway-biz"
    "/src/main/java/com/chinaservices/dsly/highway/module"
)
_SHIPPING = (
    "backend/c12-mtp/c12-mtp-shipping-service/c12-mtp-shipping-biz"
    "/src/main/java/com/chinaservices/dsly/shipping/module"
)
_BASIC = (
    "backend/c12-mtp/c12-mtp-basic-service/c12-mtp-basic-biz"
    "/src/main/java/com/chinaservices/dsly/basic/module"
)
_BASIC_ADMIN = f"{_BASIC}/address/service/AddressAdminService.java"
_BASIC_PORTAL = f"{_BASIC}/address/service/AddressPortalService.java"
_CARGO_ADMIN = f"{_BASIC}/cargo/service/CargoAdminService.java"
_CARGO_PORTAL = f"{_BASIC}/cargo/service/CargoPortalService.java"
_CARGO_BASIC_SVC = f"{_BASIC}/cargo/service/CargoBasicService.java"
_CARGO_CATEGORY_ADMIN = f"{_BASIC}/cargo/service/CargoCategoryAdminService.java"
_CARGO_CATEGORY_PORTAL_CTRL = f"{_BASIC}/cargo/controller/CargoCategoryPortalController.java"
_PRICE_ADMIN = f"{_BASIC}/basePrice/service/CargoBasePriceConfigAdminService.java"
_PRICE_BASIC = f"{_BASIC}/basePrice/service/CargoBasePriceConfigBasicService.java"
_PRICE_EDIT = (
    "frontend/c12-mtp-ui/src/views/basic/basePrice/components/cargoBasePriceConfigEdit.vue"
)
_BUSINESS_ADMIN = f"{_BASIC}/business/service/BusinessAdminService.java"
_BUSINESS_PORTAL = f"{_BASIC}/business/service/BusinessPortalService.java"
_EXPENSE_ADMIN = f"{_BASIC}/config/service/ExpenseConfigAdminService.java"
_EXPENSE_PORTAL = f"{_BASIC}/config/service/ExpenseConfigPortalService.java"
_TEMPLATE_ADMIN = f"{_BASIC}/template/service/TemplateAdminService.java"
_TEMPLATE_PORTAL = f"{_BASIC}/template/service/TemplatePortalService.java"
_SITE_FEE_ADMIN = f"{_BASIC}/siteFee/service/SiteFeeAdminService.java"
_SITE_FEE_ITEM_CTRL = f"{_BASIC}/siteFee/controller/SiteFeeItemAdminController.java"
_SITE_FEE_RANGE_BASIC = f"{_BASIC}/siteFee/service/SiteFeeItemRangeBasicService.java"
_SITE_FEE_RANGE_CTRL = f"{_BASIC}/siteFee/controller/SiteFeeItemRangeAdminController.java"
_VEHICLE_BASIC = f"{_BASIC}/vehicle/service/VehicleBasicService.java"
_DRIVER_BASIC = f"{_BASIC}/driver/service/DriverBasicService.java"
_DRIVER_ADMIN = f"{_BASIC}/driver/service/DriverAdminService.java"
_DRIVER_PORTAL = f"{_BASIC}/driver/service/DriverPortalService.java"
_DRIVER_INFO = f"{_BASIC}/driver/service/DriverInfoService.java"
_SHIP_ADMIN_CTRL = f"{_BASIC}/ship/controller/ShipAdminController.java"
_SHIP_PORTAL_CTRL = f"{_BASIC}/ship/controller/ShipPortalController.java"
_SHIP_OWNER_ADMIN_CTRL = f"{_BASIC}/shipowner/controller/ShipOwnerAdminController.java"
_SHIP_OWNER_PORTAL_CTRL = f"{_BASIC}/shipowner/controller/ShipOwnerPortalController.java"
_PORT_ADMIN_SVC = f"{_BASIC}/port/service/PortAdminService.java"
_OUTBOUND_BOX_SYNC = f"{_BASIC}/outboundbox/service/WmsOutboundBoxSyncService.java"
_LINE = (
    "backend/c12-mtp/c12-mtp-line-service/c12-mtp-line-biz"
    "/src/main/java/com/chinaservices/dsly/line/module"
)
_LINE_ROUTE_ADMIN = f"{_LINE}/route/service/RouteAdminService.java"
_LINE_ROUTE_PORTAL = f"{_LINE}/route/service/RoutePortalService.java"
_LINE_ROUTE_BASIC = f"{_LINE}/route/service/RouteBasicService.java"
_LINE_ROUTE_INQUIRY_ADMIN = f"{_LINE}/routeInquiry/service/RouteInquiryAdminService.java"
_LINE_ROUTE_INQUIRY_EDIT = (
    "frontend/c12-mtp-ui/src/views/line/routeInquiry/components/routeInquiryEdit.vue"
)
_LINE_ROUTE_PRODUCT_ADMIN = f"{_LINE}/route/service/RouteProductAdminService.java"
_LINE_ROUTE_PRODUCT_PORTAL = f"{_LINE}/route/service/RouteProductPortalService.java"
_LINE_ROUTE_PRODUCT_BASIC = f"{_LINE}/route/service/RouteProductBasicService.java"
_LINE_PRODUCT_RELATE_ADMIN = f"{_LINE}/route/service/RouteProductRelateAdminService.java"
_LINE_PRODUCT_RELATE_BASIC = f"{_LINE}/route/service/RouteProductRelateBasicService.java"
_LINE_PRODUCT_RELATE_PORTAL = f"{_LINE}/route/service/RouteProductRelatePortalService.java"
_LINE_QUOTE_PLAN_ADMIN = f"{_LINE}/routeInquiry/service/RouteInquiryQuotePlanAdminService.java"
_LINE_QUOTE_PLAN_PORTAL = f"{_LINE}/routeInquiry/service/RouteInquiryQuotePlanPortalService.java"
_LINE_STATION_ADMIN = f"{_LINE}/station/service/StationAdminService.java"
_LINE_STATION_BASIC = f"{_LINE}/station/service/StationBasicService.java"
_LINE_RAILWAY_STATION_ADMIN = f"{_LINE}/route/service/RouteRailwayStationAdminService.java"
_LINE_CARGO_CHARGE_ADMIN_CTRL = f"{_LINE}/route/controller/RouteCargoChargeAdminController.java"
_LINE_CARGO_CHARGE_RANGE_ADMIN = f"{_LINE}/route/service/RouteCargoChargeRangeAdminService.java"
_LINE_CARGO_CHARGE_RANGE_ADMIN_CTRL = (
    f"{_LINE}/route/controller/RouteCargoChargeRangeAdminController.java"
)
_LINE_APPROVAL_USER_ADMIN = f"{_LINE}/approval/service/ApprovalUserAdminService.java"
_LINE_APPROVAL_USER_CTRL = f"{_LINE}/approval/controller/ApprovalUserAdminController.java"
_LINE_APPROVAL_HISTORY_ADMIN = f"{_LINE}/approval/service/ApprovalHistoryAdminService.java"
_LINE_APPROVAL_HISTORY_CTRL = f"{_LINE}/approval/controller/ApprovalHistoryAdminController.java"
_OP = (
    "backend/c12-mtp/c12-mtp-operation-service/c12-mtp-operation-biz"
    "/src/main/java/com/chinaservices/dsly/operation/module"
)
_OP_ENTRUSTED_ADMIN = f"{_OP}/entrusted/service/OperationEntrustedAdminService.java"
_OP_ENTRUSTED_PORTAL = f"{_OP}/entrusted/service/OperationEntrustedPortalService.java"
_OP_ENTRUSTED_BASIC = f"{_OP}/entrusted/service/OperationEntrustedBasicService.java"
_OP_ORDER_ADMIN = f"{_OP}/entrustedOrder/service/OperationEntrustedOrderAdminService.java"
_OP_ORDER_BASIC = f"{_OP}/entrustedOrder/service/OperationEntrustedOrderBasicService.java"
_OP_QUOTE_ADMIN = f"{_OP}/entrustedquote/service/OperationEntrustedQuoteAdminService.java"
_OP_APPOINTMENT_ADMIN = f"{_OP}/appointment/service/AppointmentAdminService.java"
_OP_APPOINTMENT_BASIC = f"{_OP}/appointment/service/AppointmentBasicService.java"
_OP_VEHICLE = f"{_OP}/appointmentvehicle/service/AppointmentVehicleService.java"
_OP_PICKUP = f"{_OP}/pickupappointment/service/PickUpAppointmentService.java"
_OP_CONTAINER_BASIC = f"{_OP}/container/service/OperationContainerBasicService.java"
_OP_GENERAL_CARGO_BASIC = f"{_OP}/generalcargo/service/GeneralCargoBasicService.java"
_OP_WORKNODE_BASIC = f"{_OP}/worknode/service/WorkNodeBasicService.java"
_OP_ENTRUSTED_EDIT = (
    "frontend/c12-mtp-ui/src/views/operation/entrusted/components/entrustedEdit.vue"
)
_CARRIER_ADMIN = f"{_HIGHWAY}/carrier/service/HighwayCarrierOrderAdminService.java"
_CARRIER_PORTAL = f"{_HIGHWAY}/carrier/service/HighwayCarrierOrderPortalService.java"
_DISPATCH_PORTAL = f"{_HIGHWAY}/dispatch/service/HighwayDispatchOrderPortalService.java"
_DISPATCH_ADMIN = f"{_HIGHWAY}/dispatch/service/HighwayDispatchOrderAdminService.java"
_CARGO_DAO = f"{_HIGHWAY}/cargo/dao/HighwayCargoDao.java"
_INBOUND_CREATE = f"{_HIGHWAY}/inboundorder/service/MtpInboundOrderCreateService.java"
_INBOUND_ADMIN = f"{_HIGHWAY}/inboundorder/service/HighwayInboundOrderAdminService.java"
_SETTLEMENT_ADMIN = f"{_HIGHWAY}/settlement/service/SettlementAdminService.java"
_CARGO_BASIC = f"{_HIGHWAY}/cargo/service/HighwayCargoBasicService.java"
_RECORD_BASIC = f"{_HIGHWAY}/record/service/HighwayRecordBasicService.java"
_PARK_PORTAL = f"{_HIGHWAY}/parkappointment/service/HighwayParkAppointmentPortalService.java"
_DISPATCH_BOX = f"{_HIGHWAY}/dispatchbox/service/HighwayDispatchBoxPortalService.java"
_CONTAINER_PORTAL = f"{_HIGHWAY}/container/service/HighwayContainerPortalService.java"
_ATTACHMENT_BASIC = f"{_HIGHWAY}/attachment/service/HighwayAttachmentBasicService.java"
_ATTACHMENT_ADMIN = f"{_HIGHWAY}/attachment/service/HighwayAttachmentAdminService.java"
_ATTACHMENT_ADMIN_CONTROLLER = (
    f"{_HIGHWAY}/attachment/controller/HighwayAttachmentAdminController.java"
)
_ENTRUSTED_ORDER_ADMIN = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/entrustedorder/service"
    "/OrderEntrustedOrderAdminService.java"
)
_ORDER_ENTRUSTED_ADMIN = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/entrusted/service"
    "/OrderEntrustedAdminService.java"
)
_ORDER_ENTRUSTED_PORTAL = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/entrusted/service"
    "/OrderEntrustedPortalService.java"
)
_ORDER_ORDER_PORTAL = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/entrustedorder/service"
    "/OrderEntrustedOrderPortalService.java"
)
_ORDER_QUOTE_ADMIN = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/entrustedquote/service"
    "/OrderEntrustedQuoteAdminService.java"
)
_ORDER_QUOTE_PORTAL = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/entrustedquote/service"
    "/OrderEntrustedQuotePortalService.java"
)
_ORDER_WORK_PLAN_ADMIN = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/workplan/service"
    "/WorkPlanAdminService.java"
)
_ORDER_WORK_PLAN_PORTAL = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/workplan/service"
    "/WorkPlanPortalService.java"
)
_ORDER_RELATE_ADMIN = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/entrustedorderrelate/service"
    "/EntrustedOrderRelateAdminService.java"
)
_ORDER_BOOKING_BASIC = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/booking/service"
    "/BookingApplicationBasicService.java"
)
_ORDER_BOOKING_ADMIN = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/booking/service"
    "/BookingApplicationAdminService.java"
)
_ORDER_BOOKING_PORTAL = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/booking/service"
    "/BookingApplicationPortalService.java"
)
_ORDER_CONFIRM_ADMIN = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/booking/service"
    "/BookingApplicationConfirmAdminService.java"
)
_ORDER_FILE = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/entrustedorderfile/service"
    "/EntrustedOrderFileBasicService.java"
)
_ORDER_ATTACH_PORTAL = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/attachment/service"
    "/OrderAttachmentPortalService.java"
)
_ORDER_ATTACH_BASIC = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/attachment/service"
    "/OrderAttachmentBasicService.java"
)
_ORDER_WMS = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/outboundorder/service"
    "/WmsOutboundOrderSyncService.java"
)
_ORDER_TRANSPORT = (
    "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz"
    "/src/main/java/com/chinaservices/dsly/order/module/outboundorder/service"
    "/OutboundTransportFulfillmentService.java"
)
_BT = "backend/c12-mtp/c12-mtp-web-service/src/main/java/com/chinaservices/mtp/web/module"
_BT_ROUTE = f"{_BT}/btroute/service/BtRouteService.java"
_BT_DAILY = f"{_BT}/btdailyplan/service/BtDailyPlanService.java"
_BT_WAYBILL = f"{_BT}/btwaybill/service/BtWaybillService.java"
_BT_DEPARTURE = f"{_BT}/departure/service/BtDeparturePlanService.java"
_BT_DEPARTURE_STATION = f"{_BT}/departure/station/service/BtDeparturePlanStationService.java"
_BT_DEPARTURE_DAILY = f"{_BT}/departure/daily/service/BtDeparturePlanDailyPlanService.java"
_BT_DEPARTURE_CHANGE = f"{_BT}/departure/change/service/BtDeparturePlanChangeRecordService.java"
_BT_MONTHLY = f"{_BT}/monthlyentrusted/service/MonthlyEntrustedBasicService.java"
_BT_SUPPLEMENT = f"{_BT}/monthlyentrustedsupplement/service/MonthlyEntrustedSupplementService.java"
_BT_TRACKING = f"{_BT}/operation/service/BtTrainOperationTrackingService.java"
_BT_LOG = f"{_BT}/operation/operationlog/service/BtTrainOperationLogService.java"
_BT_EXCEPTION = (
    f"{_BT}/operation/exceptionrecord/service/BtTrainOperationExceptionRecordService.java"
)
_BT_TRAIN_PLAN = f"{_BT}/tranPlain/service/BtTrainPlanListService.java"
_BT_MONITOR = f"{_BT}/btmonitor/operationmonitor/service/BtTrainOperationMonitorService.java"
_SETTLE = (
    "backend/c12-mtp/c12-mtp-settlement-service/c12-mtp-settlement-biz"
    "/src/main/java/com/chinaservices/dsly/settlement/module"
)
_SETTLE_EXPENSE = f"{_SETTLE}/expense/service/ExpenseBasicService.java"
_SETTLE_BT_EXPENSE = f"{_SETTLE}/btexpense/service/BtExpenseService.java"
_SETTLE_BT_LOG = f"{_SETTLE}/btexpense/service/BtExpenseModifyLogService.java"
_SETTLE_LOG = f"{_SETTLE}/log/service/ModifyLogBasicService.java"
_SETTLE_PAYABLE = f"{_SETTLE}/payableBill/service/PayableBillBasicService.java"
_SETTLE_PAYABLE_ADMIN = f"{_SETTLE}/payableBill/service/PayableBillAdminService.java"
_SETTLE_RECEIVABLE = f"{_SETTLE}/receivableBill/service/ReceivableBillBasicService.java"
_SETTLE_APPLY = f"{_SETTLE}/paymentapply/service/PaymentApplyAdminService.java"
_SETTLE_INVOICE = f"{_SETTLE}/salesinvoice/service/SalesInvoiceAdminService.java"
_SETTLE_PREPAY = f"{_SETTLE}/prepayment/service/PrepaymentAdminService.java"
_SETTLE_PREPAY_BILL = f"{_SETTLE}/prepayment/service/PrepaymentBillBasicService.java"
_SETTLE_FUND = f"{_SETTLE}/ownerfund/service/OwnerFundAdminService.java"
_SETTLE_FLOW = f"{_SETTLE}/ownerfundflow/service/OwnerFundFlowAdminService.java"
_SETTLE_OP_FEE = f"{_SETTLE}/operationfee/service/OperationFeeService.java"
_SETTLE_PAY_CONFIRM = f"{_SETTLE}/paymentconfirmation/service/PaymentConfirmationAdminService.java"
_SETTLE_PAY_VERIFY = f"{_SETTLE}/paymentverification/service/PaymentVerificationAdminService.java"
_SETTLE_RCV_CONFIRM = f"{_SETTLE}/receiptconfirmation/service/ReceiptConfirmationAdminService.java"
_SETTLE_RCV_VERIFY = f"{_SETTLE}/receiptverification/service/ReceiptVerificationAdminService.java"
_SETTLE_COLLECTION = f"{_SETTLE}/collection/service/CollectionAdminService.java"
_SETTLE_ADVANCE = f"{_SETTLE}/advancepayment/service/AdvancePaymentAdminService.java"
_SETTLE_ATTACH = f"{_SETTLE}/attachment/service/SettlementAttachmentBasicService.java"
_DECL = (
    "backend/c12-mtp/c12-mtp-declaration-service/c12-mtp-declaration-biz"
    "/src/main/java/com/chinaservices/dsly/declaration/module"
)
_DECL_ORDER = f"{_DECL}/order/service/OrderBasicService.java"
_DECL_ORDER_ADMIN = f"{_DECL}/order/service/OrderAdminService.java"
_DECL_ORDER_PORTAL = f"{_DECL}/order/service/OrderPortalService.java"
_DECL_TRANSPORT = f"{_DECL}/transport/service/OrderTransportBasicService.java"
_DECL_TRANSPORT_ADMIN = f"{_DECL}/transport/service/OrderTransportAdminService.java"
_DECL_TRANSPORT_PORTAL = f"{_DECL}/transport/service/OrderTransportPortalService.java"
_DECL_DECLARE = f"{_DECL}/declare/service/OrderDeclareBasicService.java"
_DECL_DECLARE_ADMIN = f"{_DECL}/declare/service/OrderDeclareAdminService.java"
_DECL_DECLARE_PORTAL = f"{_DECL}/declare/service/OrderDeclarePortalService.java"
_DECL_QUARANTINE = f"{_DECL}/quarantine/service/OrderQuarantineBasicService.java"
_DECL_QUARANTINE_ADMIN = f"{_DECL}/quarantine/service/OrderQuarantineAdminService.java"
_DECL_QUARANTINE_PORTAL = f"{_DECL}/quarantine/service/OrderQuarantinePortalService.java"
_DECL_ENTERPRISE = f"{_DECL}/enterprise/service/QuarantineEnterpriseBasicService.java"
_DECL_ENTERPRISE_ADMIN = f"{_DECL}/enterprise/service/QuarantineEnterpriseAdminService.java"
_DECL_ENTERPRISE_PORTAL = f"{_DECL}/enterprise/service/QuarantineEnterprisePortalService.java"
_DECL_CARGO = f"{_DECL}/cargo/service/OrderCargoBasicService.java"
_DECL_CARGO_ADMIN = f"{_DECL}/cargo/service/OrderCargoAdminService.java"
_DECL_CARGO_PORTAL = f"{_DECL}/cargo/service/OrderCargoPortalService.java"
_DECL_ATTRIBUTE = f"{_DECL}/attribute/service/OrderCargoAttributeBasicService.java"
_DECL_ATTRIBUTE_ADMIN = f"{_DECL}/attribute/service/OrderCargoAttributeAdminService.java"
_DECL_ATTRIBUTE_PORTAL = f"{_DECL}/attribute/service/OrderCargoAttributePortalService.java"
_DECL_CONTAINER = f"{_DECL}/container/service/OrderContainerBasicService.java"
_DECL_CONTAINER_ADMIN = f"{_DECL}/container/service/OrderContainerAdminService.java"
_DECL_CONTAINER_PORTAL = f"{_DECL}/container/service/OrderContainerPortalService.java"
_DECL_DOCUMENT = f"{_DECL}/document/service/OrderDocumentBasicService.java"
_DECL_DOCUMENT_ADMIN = f"{_DECL}/document/service/OrderDocumentAdminService.java"
_DECL_DOCUMENT_PORTAL = f"{_DECL}/document/service/OrderDocumentPortalService.java"
_DECL_ENTRUST = f"{_DECL}/entrust/service/EntrustPortalService.java"
_DECL_ENTRUST_ADMIN = f"{_DECL}/entrust/service/EntrustAdminService.java"
_DECL_ATTACH = f"{_DECL}/attachment/service/AttachmentAdminService.java"
_DECL_ATTACH_BASIC = f"{_DECL}/attachment/service/AttachmentBasicService.java"
_DECL_ATTACH_PORTAL = f"{_DECL}/attachment/service/AttachmentPortalService.java"
_DECL_COMMODITY = f"{_DECL}/commodity/service/CommodityAdminService.java"
_DECL_COMMODITY_PORTAL = f"{_DECL}/commodity/service/CommodityPortalService.java"
_DECL_CATALOG = f"{_DECL}/commoditycatalog/service/CommodityCatalogAdminService.java"
_DECL_BASIC_INFO = f"{_DECL}/basicinformation/service/BasicInformationAdminService.java"
_DECL_BASIC_DATA = f"{_DECL}/commoditybasicdata/service/CommodityBasicDataAdminService.java"
_DECL_ORIGIN = f"{_DECL}/origin/service/OriginAdminService.java"
_DECL_IFACE = (
    "backend/c12-mtp/c12-mtp-declaration-interface-service"
    "/c12-mtp-declaration-interface-biz/src/main/java"
    "/com/chinaservices/dsly/declarationinterface/module"
)
_DECL_FILE = f"{_DECL_IFACE}/mq/ProxyDeclarationSendConsumer.java"
_DECL_FILE_GOODS = f"{_DECL_IFACE}/mq/GoodsDeclarationStatusUpdateEventConsumer.java"
_DECL_FILE_RESPONSE = f"{_DECL_IFACE}/mq/DeclarationResponseParseProducer.java"
_DECL_ORDER_EDIT = "frontend/c12-mtp-ui/src/views/declaration/order/edit/orderEdit.vue"
_DECL_CARGO_EDIT = "frontend/c12-mtp-ui/src/views/declaration/order/edit/cargoEdit.vue"
_MEMBER = "backend/c12-portal/c12-portal-biz/src/main/java/com/chinaservices/dsly/member/module"
_MEMBER_USER = f"{_MEMBER}/userinfo/service/UserInfoAdminService.java"
_MEMBER_USER_PORTAL = f"{_MEMBER}/userinfo/service/UserInfoPortalService.java"
_MEMBER_AUTH_DETAIL = (
    f"{_MEMBER}/useridentityauthdetail/service/MemberUserIdentityAuthDetailService.java"
)
_MEMBER_USER_AUTH_ADMIN = f"{_MEMBER}/userauthinfo/service/UserAuthInfoAdminService.java"
_MEMBER_CONTRACT = f"{_MEMBER}/contract/service/ContractAdminService.java"
_MEMBER_CONTRACT_OP = f"{_MEMBER}/contract/service/ContractOperationAdminService.java"
_MEMBER_LEVEL = f"{_MEMBER}/userinfo/service/ShipperLevelAdminService.java"
_MEMBER_LEVEL_HISTORY_CTRL = (
    f"{_MEMBER}/userinfo/controller/ShipperLevelHistoryAdminController.java"
)
_MEMBER_INVOICE = f"{_MEMBER}/invoice/service/InvoicePortalService.java"
_MEMBER_MSG = f"{_MEMBER}/messageRecipient/service/MessageRecipientBasicService.java"
_MEMBER_COMPLAIN = f"{_MEMBER}/complain/service/EntrustedOrderComplainPortalService.java"
_MEMBER_COMPLAIN_ADMIN = f"{_MEMBER}/complain/service/EntrustedOrderComplainAdminService.java"
_MEMBER_EVAL_CTRL = f"{_MEMBER}/evaluation/controller/EntrustedOrderEvaluationPortalController.java"
_MEMBER_ATTACH = f"{_MEMBER}/attachment/service/MemberAttachmentBasicService.java"
_MEMBER_ATTACH_PORTAL = f"{_MEMBER}/attachment/service/MemberAttachmentPortalService.java"
_MEMBER_RISK = f"{_MEMBER}/risk/service/ShipperRiskService.java"
_COCKPIT = f"{_MEMBER}/cockpit"
_COCKPIT_DATA = f"{_COCKPIT}/service/CockpitDataService.java"
_COCKPIT_KPI_CTRL = f"{_COCKPIT}/controller/CockpitKpiController.java"
_COCKPIT_SUMMARY_CTRL = f"{_COCKPIT}/controller/CockpitCargoSummaryController.java"
_COCKPIT_CATEGORY_CTRL = f"{_COCKPIT}/controller/CockpitCargoCategoryController.java"
_COCKPIT_ENTERPRISE_CTRL = f"{_COCKPIT}/controller/CockpitEnterpriseRankController.java"
_COCKPIT_CITY_FLOW_CTRL = f"{_COCKPIT}/controller/CockpitCityFlowController.java"
_COCKPIT_CITY_CARGO_CTRL = f"{_COCKPIT}/controller/CockpitCityFlowCargoController.java"
_COCKPIT_MAP_CTRL = f"{_COCKPIT}/controller/CockpitMapFlowController.java"
_COCKPIT_TIMELINESS_CTRL = f"{_COCKPIT}/controller/CockpitTimelinessRouteController.java"
_COCKPIT_STATION_CTRL = f"{_COCKPIT}/controller/CockpitStationTurnoverController.java"
_COCKPIT_ONTIME_SUMMARY_CTRL = f"{_COCKPIT}/controller/CockpitOntimeSummaryController.java"
_COCKPIT_ONTIME_ROUTE_CTRL = f"{_COCKPIT}/controller/CockpitOntimeRouteController.java"
_COCKPIT_CONGESTION_CTRL = f"{_COCKPIT}/controller/CockpitCongestionController.java"
_COCKPIT_ACCIDENT_CTRL = f"{_COCKPIT}/controller/CockpitAccidentController.java"
_WMS_SYNC = f"{_HIGHWAY}/inboundorder/service/WmsInboundOrderSyncService.java"
_RISK_TASK = f"{_HIGHWAY}/risk/service/HighwayRiskEvaluationTaskService.java"
_RISK_GATE = f"{_HIGHWAY}/risk/service/HighwayLoadRiskGateService.java"
_SHIPPING_ADMIN = f"{_SHIPPING}/carrier/service/ShippingCarrierOrderAdminService.java"
_SHIPPING_PORTAL = f"{_SHIPPING}/carrier/service/ShippingCarrierOrderPortalService.java"
_SHIPPING_BASE = f"{_SHIPPING}/carrier/service/CarrierOrderBaseService.java"
_SHIPPING_DISPATCH_PORTAL = f"{_SHIPPING}/dispatch/service/ShippingDispatchOrderPortalService.java"
_SHIPPING_DISPATCH_ADMIN = f"{_SHIPPING}/dispatch/service/ShippingDispatchOrderAdminService.java"
_SHIPPING_CARGO_BASIC = f"{_SHIPPING}/cargo/service/ShippingCargoBasicService.java"
_SHIPPING_SETTLEMENT_BASIC = (
    f"{_SHIPPING}/settlement/service/ShippingCarrierSettlementBasicService.java"
)
_SHIPPING_ATTACHMENT_ADMIN = f"{_SHIPPING}/attachment/service/ShippingAttachmentAdminService.java"
_SHIPPING_ATTACHMENT_ADMIN_CONTROLLER = (
    f"{_SHIPPING}/attachment/controller/ShippingAttachmentAdminController.java"
)
_SHIPPING_MANIFEST_ADMIN_CONTROLLER = (
    f"{_SHIPPING}/manifest/controller/ShippingDispatchManifestAdminController.java"
)
_SHIPPING_RECORD_BASE = f"{_SHIPPING}/record/service/RecordBaseService.java"
_RAILWAY = (
    "backend/c12-mtp/c12-mtp-railway-service/c12-mtp-railway-biz"
    "/src/main/java/com/chinaservices/dsly/railway/module"
)
_RW_CARRIER_ADMIN = f"{_RAILWAY}/carrier/service/RailwayCarrierOrderAdminService.java"
_RW_CARRIER_BASIC = f"{_RAILWAY}/carrier/service/RailwayCarrierOrderBasicService.java"
_RW_DISPATCH_BASIC = f"{_RAILWAY}/dispatch/service/RailwayDispatchOrderBasicService.java"
_RW_DISPATCH_ADMIN = f"{_RAILWAY}/dispatch/service/RailwayDispatchOrderAdminService.java"
_RW_DISPATCH_PORTAL = f"{_RAILWAY}/dispatch/service/RailwayDispatchOrderPortalService.java"
_RW_CARGO_BASIC = f"{_RAILWAY}/cargo/service/RailwayCargoBasicService.java"
_RW_RECORD_BASIC = f"{_RAILWAY}/record/service/RailwayRecordBasicService.java"
_RW_SETTLEMENT_ADMIN = f"{_RAILWAY}/settlement/service/RailwayCarrierSettlementAdminService.java"
_RW_DAILY_BASIC = f"{_RAILWAY}/dailyplan/service/RailwayDailyPlanBasicService.java"
_RW_MANIFEST_BASIC = f"{_RAILWAY}/manifest/service/RailwayDispatchManifestBasicService.java"
_RW_ATTACHMENT_BASIC = f"{_RAILWAY}/attachment/service/RailwayAttachmentBasicService.java"

SEED_TABLES: tuple[str, ...] = (
    f"{MTP}.cs_dsly_highway_cargo",
    f"{MTP}.cs_dsly_highway_carrier_order",
    f"{MTP}.cs_dsly_highway_carrier_settlement",
    f"{MTP}.cs_dsly_highway_dispatch_order",
    f"{MTP}.cs_dsly_highway_dispatch_record",
    f"{MTP}.cs_dsly_highway_inbound_order",
    f"{MTP}.cs_dsly_highway_inbound_order_cargo",
    f"{MTP}.cs_dsly_highway_park_appointment",
    f"{MTP}.cs_dsly_basic_address",
    f"{MTP}.cs_dsly_basic_cargo",
    f"{MTP}.cs_dsly_basic_cargo_category",
    f"{MTP}.cs_dsly_line_route",
    f"{MTP}.cs_dsly_line_route_inquiry",
    f"{MTP}.cs_dsly_line_route_product",
    f"{MTP}.cs_dsly_line_route_carrier",
    f"{MTP}.cs_dsly_line_route_product_relate",
    f"{MTP}.cs_dsly_line_route_relate",
    f"{MTP}.cs_dsly_line_route_railway",
    f"{MTP}.cs_dsly_line_route_railway_station",
    f"{MTP}.cs_dsly_line_route_cargo_charge",
    f"{MTP}.cs_dsly_line_route_cargo_charge_range",
    f"{MTP}.cs_dsly_line_route_inquiry_quote",
    f"{MTP}.cs_dsly_line_route_snapshot_quote",
    f"{MTP}.cs_dsly_line_route_inquiry_quote_plan",
    f"{MTP}.cs_dsly_line_station",
    f"{MTP}.cs_dsly_line_approval_user",
    f"{MTP}.cs_dsly_line_approval_history",
    f"{MTP}.cs_dsly_operation_entrusted",
    f"{MTP}.cs_dsly_operation_entrusted_order",
    f"{MTP}.cs_dsly_operation_entrusted_business_type",
    f"{MTP}.cs_dsly_operation_entrusted_business_cargo",
    f"{MTP}.cs_dsly_operation_entrusted_business_container",
    f"{MTP}.cs_dsly_operation_entrusted_quote",
    f"{MTP}.cs_dsly_operation_entrusted_quote_info",
    f"{MTP}.cs_dsly_operation_appointment",
    f"{MTP}.cs_dsly_operation_appointment_vehicle",
    f"{MTP}.cs_dsly_operation_pick_up_appointment",
    f"{MTP}.cs_dsly_operation_container",
    f"{MTP}.cs_dsly_operation_general_cargo",
    f"{MTP}.cs_dsly_operation_work_node",
    f"{MTP}.cs_dsly_operation_attachment",
    f"{MTP}.cs_dsly_order_entrusted",
    f"{MTP}.cs_dsly_order_entrusted_order",
    f"{MTP}.cs_dsly_order_entrusted_order_relate",
    f"{MTP}.cs_dsly_order_work_plan",
    f"{MTP}.cs_dsly_order_entrusted_cargo",
    f"{MTP}.cs_dsly_order_entrusted_quote",
    f"{MTP}.cs_dsly_order_entrusted_order_settlement",
    f"{MTP}.cs_dsly_order_container",
    f"{MTP}.cs_dsly_order_attachment",
    f"{MTP}.cs_dsly_order_file",
    f"{MTP}.cs_dsly_order_node",
    f"{MTP}.cs_dsly_order_booking_application",
    f"{MTP}.cs_dsly_order_booking_application_confirm",
    f"{MTP}.cs_dsly_order_outbound_order_detail",
    f"{MTP}.cs_dsly_order_outbound_entrusted_relation",
    f"{MTP}.cs_dsly_order_outbound_transport_relation",
    # cs_dsly_order_risk_evaluation_task is intentionally not seeded: Java and
    # the migration define it, but UAT has no physical table to measure yet.
    f"{MTP}.cs_dsly_shipping_carrier_order",
    f"{MTP}.cs_dsly_shipping_cargo",
    f"{MTP}.cs_dsly_shipping_dispatch_order",
    f"{MTP}.cs_dsly_shipping_carrier_settlement",
    f"{MTP}.cs_dsly_shipping_dispatch_record",
    f"{MTP}.cs_dsly_shipping_dispatch_manifest",
    f"{MTP}.cs_dsly_shipping_container",
    f"{MTP}.cs_dsly_shipping_attachment",
    f"{MTP}.cs_dsly_highway_dispatch_box_relation",
    f"{MTP}.cs_dsly_highway_risk_bypass_log",
    f"{MTP}.cs_dsly_highway_attachment",
    f"{MTP}.cs_dsly_highway_container",
    f"{MTP}.cs_dsly_highway_inbound_receipt_sync_record",
    f"{MTP}.cs_dsly_order_outbound_order",
    f"{MTP}.cs_dsly_white_enterprise",
    f"{MTP}.cs_dsly_railway_cargo",
    f"{MTP}.cs_dsly_railway_carrier_order",
    f"{MTP}.cs_dsly_railway_carrier_settlement",
    f"{MTP}.cs_dsly_railway_dispatch_order",
    f"{MTP}.cs_dsly_railway_dispatch_record",
    f"{MTP}.cs_dsly_railway_dispatch_order_line",
    f"{MTP}.cs_dsly_railway_dispatch_order_container",
    f"{MTP}.cs_dsly_railway_dispatch_manifest",
    f"{MTP}.cs_dsly_railway_daily_plan",
    f"{MTP}.cs_dsly_railway_carrier_order_container",
    f"{MTP}.cs_dsly_railway_attachment",
    # No relation at all: proves the "只看有关联的表" filter really hides tables.
    # attachment/container source_id is polymorphic (承运单/运单/集装箱)，不能建单一父表边。
    f"{MTP}.cs_dsly_basic_port",
    f"{MTP}.cs_dsly_basic_billing_template",
    f"{MTP}.cs_dsly_basic_business_info",
    f"{MTP}.cs_dsly_basic_cargo_base_price_config",
    f"{MTP}.cs_dsly_basic_cargo_external",
    f"{MTP}.cs_dsly_basic_driver",
    f"{MTP}.cs_dsly_basic_driver_info",
    f"{MTP}.cs_dsly_basic_expense_config",
    f"{MTP}.cs_dsly_basic_outbound_box",
    f"{MTP}.cs_dsly_basic_ship",
    f"{MTP}.cs_dsly_basic_ship_owner",
    f"{MTP}.cs_dsly_basic_site_fee_item",
    f"{MTP}.cs_dsly_basic_site_fee_item_business",
    f"{MTP}.cs_dsly_basic_site_fee_item_range",
    f"{MTP}.cs_dsly_basic_vehicle",
    f"{MTP}.cs_bt_route",
    f"{MTP}.cs_bt_route_station",
    f"{MTP}.cs_bt_daily_plan",
    f"{MTP}.cs_bt_daily_plan_box",
    f"{MTP}.cs_bt_departure_plan",
    f"{MTP}.cs_bt_departure_plan_station",
    f"{MTP}.cs_bt_departure_plan_daily_plan",
    f"{MTP}.cs_bt_departure_plan_change_record",
    f"{MTP}.cs_bt_monthly_entrusted",
    f"{MTP}.cs_bt_monthly_entrusted_supplement",
    f"{MTP}.cs_bt_waybill",
    f"{MTP}.cs_bt_waybill_box",
    f"{MTP}.cs_bt_waybill_voucher",
    f"{MTP}.cs_bt_train_operation_tracking",
    f"{MTP}.cs_bt_train_operation_log",
    f"{MTP}.cs_bt_train_operation_exception_record",
    f"{MTP}.cs_dsly_settlement_expense",
    f"{MTP}.cs_dsly_settlement_expense_modify_log",
    f"{MTP}.cs_dsly_settlement_bt_expense",
    f"{MTP}.cs_dsly_settlement_bt_expense_modify_log",
    f"{MTP}.cs_dsly_settlement_payable_bill",
    f"{MTP}.cs_dsly_settlement_receivable_bill",
    f"{MTP}.cs_dsly_settlement_payment_apply",
    f"{MTP}.cs_dsly_settlement_payment_relation",
    f"{MTP}.cs_dsly_settlement_payment_approval_history",
    f"{MTP}.cs_dsly_settlement_sales_invoice",
    f"{MTP}.cs_dsly_settlement_prepayment",
    f"{MTP}.cs_dsly_settlement_prepayment_bill",
    f"{MTP}.cs_dsly_settlement_owner_fund",
    f"{MTP}.cs_dsly_settlement_owner_fund_flow",
    f"{MTP}.cs_dsly_settlement_operation_fee",
    f"{MTP}.cs_dsly_settlement_operation_fee_detail",
    f"{MTP}.cs_dsly_settlement_operation_cargo_detail",
    f"{MTP}.cs_dsly_settlement_payment_confirmation",
    f"{MTP}.cs_dsly_settlement_payment_verification",
    f"{MTP}.cs_dsly_settlement_receipt_confirmation",
    f"{MTP}.cs_dsly_settlement_receipt_verification",
    f"{MTP}.cs_dsly_settlement_collection",
    f"{MTP}.cs_dsly_settlement_advance_payment",
    f"{MTP}.cs_dsly_settlement_attachment",
    f"{MTP}.cs_bt_station",
    f"{MTP}.cs_dsly_declaration_order",
    f"{MTP}.cs_dsly_declaration_order_transport",
    f"{MTP}.cs_dsly_declaration_order_declare",
    f"{MTP}.cs_dsly_declaration_order_quarantine",
    f"{MTP}.cs_dsly_declaration_order_quarantine_enterprise",
    f"{MTP}.cs_dsly_declaration_order_cargo",
    f"{MTP}.cs_dsly_declaration_order_cargo_attribute",
    f"{MTP}.cs_dsly_declaration_order_container",
    f"{MTP}.cs_dsly_declaration_order_document",
    f"{MTP}.cs_dsly_declaration_entrust",
    f"{MTP}.cs_dsly_declaration_attachment",
    f"{MTP}.cs_dsly_declaration_commodity",
    f"{MTP}.cs_dsly_declaration_commodity_catalog",
    f"{MTP}.cs_dsly_declaration_commodity_basic_data",
    f"{MTP}.cs_dsly_declaration_basic_information",
    f"{MTP}.cs_dsly_declaration_origin",
    f"{MTP}.cs_dsly_declaration_interface_file_transfer_record",
    f"{PORTAL}.cs_portal_member_user_info",
    f"{PORTAL}.cs_portal_member_user_auth_info",
    f"{PORTAL}.cs_portal_member_user_identity_auth_detail",
    f"{PORTAL}.cs_portal_member_contract",
    f"{PORTAL}.cs_portal_member_contract_operation",
    f"{PORTAL}.cs_portal_member_contract_quote_info",
    f"{PORTAL}.cs_portal_member_contract_attachment",
    f"{PORTAL}.cs_portal_member_shipper_level",
    f"{PORTAL}.cs_portal_member_shipper_level_history",
    f"{PORTAL}.cs_portal_member_attachment",
    f"{PORTAL}.cs_portal_member_invoice",
    f"{PORTAL}.cs_portal_member_message_recipient",
    f"{PORTAL}.cs_portal_member_entrusted_order_complain",
    f"{PORTAL}.cs_portal_member_entrusted_order_evaluation",
    f"{PORTAL}.cs_portal_cockpit_kpi",
    f"{PORTAL}.cs_portal_cockpit_cargo_summary",
    f"{PORTAL}.cs_portal_cockpit_cargo_category",
    f"{PORTAL}.cs_portal_cockpit_enterprise_rank",
    f"{PORTAL}.cs_portal_cockpit_city_flow",
    f"{PORTAL}.cs_portal_cockpit_city_flow_cargo",
    f"{PORTAL}.cs_portal_cockpit_map_flow",
    f"{PORTAL}.cs_portal_cockpit_timeliness_route",
    f"{PORTAL}.cs_portal_cockpit_station_turnover",
    f"{PORTAL}.cs_portal_cockpit_ontime_summary",
    f"{PORTAL}.cs_portal_cockpit_ontime_route",
    f"{PORTAL}.cs_portal_cockpit_congestion",
    f"{PORTAL}.cs_portal_cockpit_accident",
)

SEED_EDGES: tuple[SeedEdge, ...] = (
    # ---- The two disagreements that survived being written down. Both are the
    # same shape: the parent key arrives from the caller, so one request can carry
    # it twice, and the rows simply never have.
    #
    # Six relations used to sit here. Recording the sites took four of them away,
    # and all four had gone wrong in one place: a ``batchInsert`` had been read as
    # many children per parent when the loop around it was minting a fresh parent
    # key each pass and hanging exactly one child on it. The batch was wide, not
    # deep. That is the reading ``check_sites`` now refuses to accept unsupported.
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_carrier_order.carrier_order_no",
        child=f"{MTP}.cs_dsly_highway_cargo.carrier_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        # 200 cargo rows, but only the 107 carrier-order ones fill this column: the
        # other 93 arrive through the dispatch path and fill the column below.
        measured=SeedMeasurement("text", 200, 107, 107, 107, 107),
        reason="承运单号由入参带进来，同一批拆段里没有任何东西阻止两条货物用同一个单号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_CARRIER_ADMIN,
                method="batchCreateCarrierOrder",
                snippet=(
                    "for(CarrierOrderAdminChildItem carrierOrderChildItem :"
                    " carrierOrderAdminChildItemList){\n"
                    "    String carrierOrderNo = carrierOrderChildItem.getCarrierOrderNo();\n"
                    "    HighwayCargo cargo = buildCarrierCargo("
                    "cargoAdminQuery, carrierOrderChildItem, carrierOrderNo);\n"
                    "    insertCargoList.add(cargo);\n"
                    "}\n"
                    "cargoDao.batchInsert(insertCargoList);"
                ),
            ),
            SeedSite(
                kind="lossy_read",
                file=_CARGO_DAO,
                method="findByCarrierOrderNo",
                snippet=(
                    "conditionRule.andEqual(HighwayCargo::getCarrierOrderNo, carrierOrderNo);\n"
                    "return findFirst(conditionRule);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_carrier_order.carrier_order_no",
        child=f"{MTP}.cs_dsly_highway_carrier_settlement.carrier_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 107, 107, 107, 107, 107),
        reason="结算和货物在同一个循环里按同一个入参单号生成，同样挡不住第二条",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_CARRIER_ADMIN,
                method="batchCreateCarrierOrder",
                snippet=(
                    "Settlement settlement = buildSettlement("
                    "carrierOrderChildItem, carrierOrderNo);\n"
                    "insertSettlementList.add(settlement);\n"
                    "// ...\n"
                    "settlementAdminService.batchInsert(insertSettlementList);"
                ),
            ),
        ),
    ),
    # ---- Where the code verdict was corrected. A fresh parent key per iteration
    # with one child attached to it is one-to-one however it reaches the database.
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_dispatch_order.dispatch_order_no",
        child=f"{MTP}.cs_dsly_highway_cargo.dispatch_order_no",
        code_cardinality="one_to_one",
        code_evidence="enforced",
        measured=SeedMeasurement("text", 200, 93, 93, 93, 93),
        reason="派车单号在循环里新生成，一号一货；读侧的严格 toMap 一旦重复就会抛异常",
        sites=(
            SeedSite(
                kind="fresh_key_per_row",
                file=_CARRIER_PORTAL,
                method="batchDispatchOrder",
                snippet=(
                    "String dispatchOrderNo = SequenceClient.getSingleWithSystemCode(\n"
                    "        SourceEnum.MULTIMODAL_TRANSPORT.getCode(),"
                    " HighwayOrderNoEnum.DISPATCH_ORDER_NO.getCode());\n"
                    "HighwayCargo dispatchCargo = buildDispatchCargo("
                    "carrierCargo, dispatchOrderNo, dispatchChildItem);\n"
                    "insertCargoList.add(dispatchCargo);"
                ),
            ),
            # The strongest thing the code dimension can produce, and the reason
            # this one is 强制 rather than 单写: the JDK throws on a repeated key,
            # so 93 rows having gone through here is the data attesting to its own
            # uniqueness. Only citable because there are rows -- see the shipping
            # relation below, where the identical construct has never executed.
            SeedSite(
                kind="strict_to_map",
                file=_CARRIER_PORTAL,
                method="batchDispatchOrder",
                snippet=(
                    "cargoMap = cargoList.stream().collect(Collectors.toMap(\n"
                    "        HighwayCargo::getDispatchOrderNo, Function.identity()));"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_white_enterprise.id",
        child=f"{MTP}.cs_dsly_highway_risk_bypass_log.whitelist_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 5, 5),
        reason="绕过日志按次记录命中的白名单，同一白名单可被多次复用；UAT 尚无日志",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RISK_GATE,
                method="saveBypassLog",
                snippet="log.setWhitelistId(whitelist.whitelistId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_white_enterprise.white_no",
        child=f"{MTP}.cs_dsly_highway_risk_bypass_log.white_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 5, 5),
        reason="绕过日志同时固化白名单编号，同一编号可出现在多次放行日志中；UAT 尚无日志",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RISK_GATE,
                method="saveBypassLog",
                snippet="log.setWhiteNo(whitelist.whiteNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_address.id",
        child=f"{MTP}.cs_dsly_highway_carrier_order.address_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        # 951 addresses on file, 107 orders using 107 of them. The old verdict read
        # that as reuse being available and declined; the write path never reuses.
        measured=SeedMeasurement("numeric", 107, 107, 107, 951, 951),
        reason="每次循环都新存一条地址再挂给这一张单，地址主数据从不复用",
        sites=(
            SeedSite(
                kind="fresh_key_per_row",
                file=_CARRIER_ADMIN,
                method="batchCreateCarrierOrder",
                snippet=(
                    "Long addressId = remoteAdminService.saveAddress(addressAdminItem);\n"
                    "            carrierOrder.setAddressId(addressId);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_inbound_order.inbound_order_no",
        child=f"{MTP}.cs_dsly_highway_inbound_order_cargo.inbound_order_no",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("text", 7, 7, 7, 7, 7),
        # The old reason claimed batch writing here. There is no batch call in
        # this path at all, which is the sort of thing a site list makes hard to
        # keep asserting.
        reason="入库单落库后只建一条货物快照，单对象 saveOrUpdate，路径上没有批量写入",
        sites=(
            SeedSite(
                kind="fresh_key_per_row",
                file=_INBOUND_CREATE,
                method="createAndPublish",
                snippet=(
                    "HighwayInboundOrder inboundOrder = buildInboundOrder("
                    "dispatchOrder, carrierOrder, source, loadTime, now);\n"
                    "inboundOrderDao.saveOrUpdate(inboundOrder);\n"
                    "HighwayInboundOrderCargo inboundCargo = buildInboundCargo("
                    "inboundOrder, cargo, estimatedNumber);\n"
                    "inboundOrderCargoDao.saveOrUpdate(inboundCargo);"
                ),
            ),
        ),
    ),
    # ---- Both dimensions agree on one-to-many.
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo_category.id",
        child=f"{MTP}.cs_dsly_highway_cargo.category_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 200, 184, 5, 8, 8),
        reason="品类是可复用的主数据，父键取自既有数据而非新建",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_CARRIER_ADMIN,
                method="buildCarrierCargo",
                snippet="cargoQuery.setCategoryId(cargoAdminQuery.getCategoryId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo.id",
        child=f"{MTP}.cs_dsly_highway_cargo.cargo_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        # The one relation with real orphans: 51 keys in use against 48 surviving
        # cargo rows, and 27 of those keys resolve to nothing. Both dimensions call
        # this a healthy one-to-many; only the join test finds the problem.
        measured=SeedMeasurement("numeric", 200, 200, 51, 48, 48, orphan_keys=27),
        reason="货物主数据同样可复用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_CARRIER_ADMIN,
                method="buildCarrierCargo",
                snippet="cargoQuery.setCargoId(cargoAdminQuery.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_carrier_order.carrier_order_no",
        child=f"{MTP}.cs_dsly_highway_dispatch_order.carrier_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 93, 93, 78, 107, 107),
        reason="一张承运单可以拆成多次派车",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_CARRIER_PORTAL,
                method="batchDispatchOrder",
                snippet=(
                    "HighwayDispatchOrder dispatchOrder = buildDispatchOrder(\n"
                    "        carrierOrder, dispatchOrderNo, dispatchChildItem);\n"
                    "insertDispatchOrderList.add(dispatchOrder);\n"
                    "dispatchOrderDao.batchInsert(insertDispatchOrderList);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_dispatch_order.dispatch_order_no",
        child=f"{MTP}.cs_dsly_highway_dispatch_record.dispatch_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 281, 281, 93, 93, 93),
        reason="派车流水按状态变更逐条追加",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RECORD_BASIC,
                method="buildRouteItem",
                snippet=(
                    "record.setOperatorTime(date);\n"
                    "record.setDispatchOrderNo(dispatchOrderNo);\n"
                    "return record;"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_dispatch_order.dispatch_order_no",
        child=f"{MTP}.cs_dsly_highway_park_appointment.dispatch_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        # Only 11 rows, well under the threshold, yet the verdict is measured
        # rather than low-sample: a key has already been seen twice, and no amount
        # of further rows can unsee it.
        measured=SeedMeasurement("text", 11, 11, 8, 93, 93),
        reason="一次派车可以预约多次进园",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_PARK_PORTAL,
                method="buildAppointment",
                snippet=(
                    "HighwayParkAppointment appointment = new HighwayParkAppointment();\n"
                    "appointment.setDispatchOrderId(dispatchOrder.getId());\n"
                    "appointment.setDispatchOrderNo(dispatchOrder.getDispatchOrderNo());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route.id",
        child=f"{MTP}.cs_dsly_line_route_carrier.route_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 497, 497, 263, 259, 259, orphan_keys=5),
        reason="一条线路挂多个承运商，铁路保存循环复用 routeId；UAT 平均约 1.9 个，5 个孤儿键",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_LINE_ROUTE_ADMIN,
                method="saveRouteRailway",
                snippet=(
                    "for (RouteCarrierItem routeCarrierItem : routeCarrierList) {\n"
                    "            routeCarrierItem.setRouteId(routeId);"
                ),
            ),
            SeedSite(
                kind="caller_key_reuse",
                file=_LINE_ROUTE_ADMIN,
                method="saveRouteDetails",
                snippet="routeCarrier.setRouteId(route.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted_order.entrusted_order_no",
        child=f"{MTP}.cs_dsly_order_entrusted_order_relate.entrusted_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 129, 129, 74, 81, 81),
        reason="一个委托订单拆成多个承运订单",
    ),
    # ---- A dead column: declared beside the one that is actually used, never
    # written. It stays stored and counted, and the page keeps it off the list.
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted_order.id",
        child=f"{MTP}.cs_dsly_order_entrusted_order_relate.entrusted_order_id",
        code_cardinality="unknown",
        code_evidence="no_write_path",
        # The table holds 129 rows and this column holds none of them, which is
        # what tells a dead column apart from a table nobody has used yet.
        measured=SeedMeasurement("numeric", 129, 0, 0, 81, 81),
        reason="写入路径只赋 entrusted_order_no，从不赋这一列",
    ),
    # ---- A domain that was never switched on. The code still answers, which is
    # the whole reason the two dimensions are kept apart. This is also the one
    # relation where an empty table changes what the code is allowed to claim:
    # the strict ``toMap`` below asserts uniqueness exactly as the highway one
    # does, but with nothing ever having passed through it, it has never had the
    # chance to throw. The structural assertion stands; the runtime attestation
    # that makes the highway relation persuasive is simply absent here.
    SeedEdge(
        parent=f"{MTP}.cs_dsly_shipping_carrier_order.carrier_order_no",
        child=f"{MTP}.cs_dsly_shipping_cargo.carrier_order_no",
        code_cardinality="one_to_one",
        code_evidence="enforced",
        measured=SeedMeasurement("text", 0, 0, 0, 0, 0),
        reason="承运单号已存在就跳过，一单一货；水路两个环境都未投产，数据侧无从验证",
        sites=(
            SeedSite(
                kind="unique_guard",
                file=_SHIPPING_ADMIN,
                method="batchCreateCarrierOrder",
                snippet=(
                    "if(Objects.nonNull(optionalMap.get("
                    "shippingCarrierOrderAdminChildItem.getCarrierOrderNo()))){"
                ),
            ),
            SeedSite(
                kind="single_write",
                file=_SHIPPING_ADMIN,
                method="batchCreateCarrierOrder",
                snippet="cargoDao.saveOrUpdate(cargo);",
            ),
            SeedSite(
                kind="strict_to_map",
                file=_SHIPPING_BASE,
                method="getCarrierInfoList",
                snippet=(
                    "Map<String, ShippingCargoQuery> cargoMap = cargoQueryList.stream().collect(Collectors.toMap("
                    "ShippingCargoQuery::getCarrierOrderNo, Function.identity()));"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_dispatch_order.dispatch_order_no",
        child=f"{MTP}.cs_dsly_highway_inbound_order.dispatch_order_no",
        code_cardinality="one_to_one",
        code_evidence="enforced",
        measured=SeedMeasurement("text", 7, 7, 7, 93, 93),
        reason="同一派车单只允许生成一张入库单，已存在则幂等返回",
        sites=(
            SeedSite(
                kind="unique_guard",
                file=_INBOUND_CREATE,
                method="createAndPublish",
                snippet=(
                    "if (existed != null) {\n"
                    '    log.info("platform warehouse inbound order already exists, '
                    'dispatchOrderNo={}, inboundOrderNo={}",'
                ),
            ),
            SeedSite(
                kind="single_write",
                file=_INBOUND_CREATE,
                method="buildInboundOrder",
                snippet=(
                    "inboundOrder.setDispatchOrderId(dispatchOrder.getId());\n"
                    "inboundOrder.setDispatchOrderNo(\n"
                    "        dispatchOrder.getDispatchOrderNo());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_dispatch_order.id",
        child=f"{MTP}.cs_dsly_highway_inbound_order.dispatch_order_id",
        code_cardinality="one_to_one",
        code_evidence="enforced",
        measured=SeedMeasurement("numeric", 7, 7, 7, 93, 93),
        reason="入库单同时写下派车主键，和单号同一条幂等路径",
        sites=(
            SeedSite(
                kind="unique_guard",
                file=_INBOUND_CREATE,
                method="createAndPublish",
                snippet=(
                    "HighwayInboundOrder existed =\n"
                    "        inboundOrderDao.findByDispatchOrderNo(\n"
                    "                dispatchOrder.getDispatchOrderNo());\n"
                    "if (existed != null) {"
                ),
            ),
            SeedSite(
                kind="single_write",
                file=_INBOUND_CREATE,
                method="buildInboundOrder",
                snippet=(
                    "inboundOrder.setDispatchOrderId(dispatchOrder.getId());\n"
                    "inboundOrder.setDispatchOrderNo(\n"
                    "        dispatchOrder.getDispatchOrderNo());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_dispatch_order.dispatch_order_no",
        child=f"{MTP}.cs_dsly_highway_dispatch_box_relation.dispatch_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 31, 31, 28, 93, 93),
        reason="一单可以挂多个箱码，循环外的派车单号整批共用",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_DISPATCH_BOX,
                method="sync",
                snippet=(
                    "List<HighwayDispatchBoxRelation> inserts = validated.stream().map(query -> {\n"
                    "    HighwayDispatchBoxRelation relation = new HighwayDispatchBoxRelation();\n"
                    "    relation.setDispatchOrderId(dispatchOrder.getId());\n"
                    "    relation.setDispatchOrderNo(dispatchOrder.getDispatchOrderNo());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_dispatch_order.id",
        child=f"{MTP}.cs_dsly_highway_dispatch_box_relation.dispatch_order_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 31, 31, 28, 93, 93),
        reason="箱码关联同时写下派车主键，和单号同一批插入",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_DISPATCH_BOX,
                method="sync",
                snippet=(
                    "relation.setDispatchOrderId(dispatchOrder.getId());\n"
                    "relation.setDispatchOrderNo(dispatchOrder.getDispatchOrderNo());\n"
                    "relation.setOutboundOrderId(query.getOutboundOrderId());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_dispatch_order.id",
        child=f"{MTP}.cs_dsly_highway_park_appointment.dispatch_order_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 11, 11, 8, 93, 93),
        reason="预约同时写下派车主键；拒绝后允许再约，一单多行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_PARK_PORTAL,
                method="buildAppointment",
                snippet=(
                    "appointment.setDispatchOrderId(dispatchOrder.getId());\n"
                    "appointment.setDispatchOrderNo(dispatchOrder.getDispatchOrderNo());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_address.id",
        child=f"{MTP}.cs_dsly_highway_dispatch_order.address_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 94, 94, 78, 951, 951),
        reason="派车单拷承运单已有的地址主键，同一地址可被多次派车复用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_CARRIER_PORTAL,
                method="buildDispatchOrder",
                snippet=(
                    "//运输订单和承运订单地址信息相同\n"
                    "        dispatchOrder.setAddressId(carrierOrder.getAddressId());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_dispatch_order.dispatch_order_no",
        child=f"{MTP}.cs_dsly_highway_risk_bypass_log.dispatch_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 93, 93),
        reason="白名单绕过按次记日志，一单可多次放行；UAT 还没有行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RISK_GATE,
                method="saveBypassLog",
                snippet=(
                    "HighwayRiskBypassLog log = new HighwayRiskBypassLog();\n"
                    "log.setDispatchOrderNo(dispatchOrder.getDispatchOrderNo());\n"
                    "log.setOperationNode(operationNode);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted_order.entrusted_order_no",
        child=f"{MTP}.cs_dsly_highway_carrier_order.entrusted_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 107, 107, 76, 89, 89),
        reason="委托单号从拆段入参拷到承运单，同一委托可拆多张承运单",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_CARRIER_ADMIN,
                method="batchCreateCarrierOrder",
                snippet=(
                    "HighwayCarrierOrder carrierOrder = GenericBeanConverter.convert("
                    "carrierOrderChildItem, HighwayCarrierOrder.class);\n"
                    "String carrierOrderNo = carrierOrderChildItem.getCarrierOrderNo();\n"
                    "carrierOrder.setCarrierOrderNo(carrierOrderNo);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route.route_no",
        child=f"{MTP}.cs_dsly_highway_carrier_order.route_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 107, 107, 96, 259, 259),
        reason="路线编号取自拆段入参既有主数据，可被多张承运单复用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_CARRIER_ADMIN,
                method="batchCreateCarrierOrder",
                snippet="carrierOrder.setRouteNo(carrierOrderChildItem.getRouteNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_inbound_order.id",
        child=f"{MTP}.cs_dsly_highway_inbound_order_cargo.inbound_order_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 7, 7, 7, 7, 7),
        reason="入库单落库后立刻挂一条货物快照，主键与单号同一路径",
        sites=(
            SeedSite(
                kind="fresh_key_per_row",
                file=_INBOUND_CREATE,
                method="createAndPublish",
                snippet=(
                    "inboundOrderDao.saveOrUpdate(inboundOrder);\n"
                    "\n"
                    "        HighwayInboundOrderCargo inboundCargo =\n"
                    "                buildInboundCargo(\n"
                    "                        inboundOrder, cargo, estimatedNumber);\n"
                    "        inboundOrderCargoDao.saveOrUpdate(inboundCargo);"
                ),
            ),
            SeedSite(
                kind="single_write",
                file=_INBOUND_CREATE,
                method="buildInboundCargo",
                snippet="inboundCargo.setInboundOrderId(inboundOrder.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo.id",
        child=f"{MTP}.cs_dsly_highway_inbound_order_cargo.cargo_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 7, 7, 5, 48, 48, orphan_keys=1),
        reason="入库快照拷运输货物已有的主数据主键，同一货物可进多张入库单",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_INBOUND_CREATE,
                method="buildInboundCargo",
                snippet="inboundCargo.setCargoId(cargo.getCargoId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_inbound_order.id",
        child=f"{MTP}.cs_dsly_highway_inbound_receipt_sync_record.inbound_order_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 2, 2, 2, 7, 7),
        reason="收货回执按 receiveNo 幂等，同一入库单可以有多次收货",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_WMS_SYNC,
                method="buildReceiptRecord",
                snippet=(
                    "record.setInboundOrderId(inboundOrder.getId());\n"
                    "record.setInboundOrderNo(inboundOrder.getInboundOrderNo());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_highway_inbound_order.inbound_order_no",
        child=f"{MTP}.cs_dsly_highway_inbound_receipt_sync_record.inbound_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 2, 2, 2, 7, 7),
        reason="回执同时记下入库单号；幂等键是 receiveNo 而不是入库单号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_WMS_SYNC,
                method="buildReceiptRecord",
                snippet="record.setInboundOrderNo(inboundOrder.getInboundOrderNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo.id",
        child=f"{MTP}.cs_dsly_highway_inbound_receipt_sync_record.cargo_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 2, 2, 2, 48, 48),
        reason="回执拷入库商品快照上的货物主键，主数据可复用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_WMS_SYNC,
                method="buildReceiptRecord",
                snippet="record.setCargoId(cargo.getCargoId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_outbound_order.id",
        child=f"{MTP}.cs_dsly_highway_dispatch_box_relation.outbound_order_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 31, 31, 11, 28, 28),
        reason="装箱明细从已校验的出库箱码拷出库主键，一单多箱可共享同一出库单",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_DISPATCH_BOX,
                method="sync",
                snippet=(
                    "relation.setDispatchOrderId(dispatchOrder.getId());\n"
                    "relation.setDispatchOrderNo(dispatchOrder.getDispatchOrderNo());\n"
                    "relation.setOutboundOrderId(query.getOutboundOrderId());\n"
                    "relation.setOutboundOrderNo(query.getOutboundOrderNo());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_outbound_order.outbound_order_no",
        child=f"{MTP}.cs_dsly_highway_dispatch_box_relation.outbound_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 31, 31, 11, 28, 28),
        reason="装箱明细同时写下出库单号，复用规则与出库主键相同",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_DISPATCH_BOX,
                method="sync",
                snippet="relation.setOutboundOrderNo(query.getOutboundOrderNo());",
            ),
        ),
    ),
    # ---- Railway domain (cs_dsly_railway_*). cargo_id is overloaded: carrier rows
    # point at basic_cargo.id, dispatch rows point at the carrier-level
    # railway_cargo.id, so that column is not seeded as a single parent edge.
    SeedEdge(
        parent=f"{MTP}.cs_dsly_railway_carrier_order.carrier_order_no",
        child=f"{MTP}.cs_dsly_railway_dispatch_order.carrier_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 21, 21, 20, 31, 31),
        reason="一张承运单可以拆成多次派车；UAT 已有一单两行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RW_CARRIER_BASIC,
                method="buildDispatchOrder",
                snippet="dispatchOrderQuery.setCarrierOrderNo(carrierOrderQuery.getCarrierOrderNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_railway_carrier_order.carrier_order_no",
        child=f"{MTP}.cs_dsly_railway_cargo.carrier_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 52, 31, 31, 31, 31),
        reason="承运货物行填承运单号；同一批拆段里不阻止两条货物共用单号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RW_CARRIER_ADMIN,
                method="buildCarrierCargo",
                snippet="cargoQuery.setCarrierOrderNo(carrierOrderNo);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_railway_dispatch_order.dispatch_order_no",
        child=f"{MTP}.cs_dsly_railway_cargo.dispatch_order_no",
        code_cardinality="one_to_one",
        code_evidence="enforced",
        measured=SeedMeasurement("text", 52, 21, 21, 21, 21),
        reason="派车单号在循环里新生成，一号一货；读侧 toMap 一旦重复就会抛异常",
        sites=(
            SeedSite(
                kind="fresh_key_per_row",
                file=_RW_DISPATCH_BASIC,
                method="batchDispatchOrderGt",
                snippet=(
                    "String dispatchOrderNo = SequenceClient.getSingle("
                    "RailwayOrderNoEnum.DISPATCH_ORDER_NO.getName());"
                ),
            ),
            SeedSite(
                kind="strict_to_map",
                file=_RW_DISPATCH_BASIC,
                method="batchDispatchOrderGt",
                snippet=(
                    "cargoMap = cargoList.stream().collect(Collectors.toMap("
                    "RailwayCargoQuery::getDispatchOrderNo, Function.identity()));"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo_category.id",
        child=f"{MTP}.cs_dsly_railway_cargo.category_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 52, 47, 4, 8, 8),
        reason="品类取自货物主数据，可被多行复用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RW_CARRIER_ADMIN,
                method="buildCarrierCargo",
                snippet="cargoQuery.setCategoryId(cargoAdminQuery.getCategoryId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_railway_carrier_order.carrier_order_no",
        child=f"{MTP}.cs_dsly_railway_carrier_settlement.railway_carrier_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 31, 31, 31, 31, 31),
        reason="结算和货物在同一循环里按入参单号生成，代码挡不住第二条",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RW_CARRIER_ADMIN,
                method="buildSettlement",
                snippet="settlementQuery.setRailwayCarrierNo(carrierOrderNo);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted_order.entrusted_order_no",
        child=f"{MTP}.cs_dsly_railway_carrier_order.entrusted_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 31, 31, 31, 89, 89),
        reason="委托单号从拆段入参拷到承运单，同一委托可拆多张",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RW_CARRIER_ADMIN,
                method="batchCreateCarrierOrder",
                snippet=(
                    "RailwayCarrierOrder carrierOrder = GenericBeanConverter.convert("
                    "carrierOrderChildItem, RailwayCarrierOrder.class);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route.route_no",
        child=f"{MTP}.cs_dsly_railway_carrier_order.route_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 31, 31, 31, 259, 259),
        reason="路线编号取自拆段入参既有主数据，可被多张承运单复用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RW_CARRIER_ADMIN,
                method="batchCreateCarrierOrder",
                snippet="carrierOrder.setRouteNo(carrierOrderChildItem.getRouteNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_railway_dispatch_order.dispatch_order_no",
        child=f"{MTP}.cs_dsly_railway_dispatch_record.dispatch_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 138, 138, 21, 21, 21),
        reason="装货/发车/抵达/卸货/签收等节点各记一条轨迹",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RW_RECORD_BASIC,
                method="buildRouteItem",
                snippet="route.setDispatchOrderNo(dispatchOrderNo);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_railway_dispatch_order.dispatch_order_no",
        child=f"{MTP}.cs_dsly_railway_dispatch_order_line.dispatch_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 48, 48, 21, 21, 21),
        reason="一张运单挂多条运行线站点",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RW_CARRIER_BASIC,
                method="batchDispatchOrder",
                snippet="deliverLine.setDispatchOrderNo(dispatchOrderNo);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_railway_dispatch_order.id",
        child=f"{MTP}.cs_dsly_railway_dispatch_manifest.dispatch_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 3, 3, 3, 21, 21),
        reason="货票/箱单可按运单批量插入多行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RW_DISPATCH_BASIC,
                method="batchDispatchOrderGt",
                snippet="item.setDispatchId(dispatchOrder.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo_category.id",
        child=f"{MTP}.cs_dsly_railway_dispatch_manifest.category_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 3, 3, 2, 8, 8),
        reason="舱单品类取自货物主数据，同一品类可被多条舱单复用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RW_DISPATCH_ADMIN,
                method="updateOrCreateManifest",
                snippet="newManifest.setCategoryId(query.getCategoryId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_railway_carrier_order.id",
        child=f"{MTP}.cs_dsly_railway_daily_plan.carrier_order_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 31, 31),
        reason="绑定日计划时同一承运单主键可挂多条计划；UAT 尚无行",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_RW_DAILY_BASIC,
                method="bindDailyPlan",
                snippet="dailyPlan.setCarrierOrderId(carrierOrderId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_railway_carrier_order.carrier_order_no",
        child=f"{MTP}.cs_dsly_railway_daily_plan.carrier_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 31, 31),
        reason="日计划同时记下承运单号，复用规则与主键相同",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_RW_DAILY_BASIC,
                method="bindDailyPlan",
                snippet="dailyPlan.setCarrierOrderNo(carrierOrderNo);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_railway_daily_plan.id",
        child=f"{MTP}.cs_dsly_railway_dispatch_order.daily_plan_id",
        code_cardinality="unknown",
        code_evidence="no_write_path",
        measured=SeedMeasurement("numeric", 21, 0, 0, 0, 0),
        reason="实体有 daily_plan_id，biz 里没有任何 setDailyPlanId",
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_railway_dispatch_order.id",
        child=f"{MTP}.cs_dsly_railway_dispatch_order_container.dispatch_order_id",
        code_cardinality="unknown",
        code_evidence="no_write_path",
        measured=SeedMeasurement("numeric", 0, 0, 0, 21, 21),
        reason="表和列在，railway-biz 没有写入路径",
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_railway_dispatch_order.dispatch_order_no",
        child=f"{MTP}.cs_dsly_railway_dispatch_order_container.dispatch_order_no",
        code_cardinality="unknown",
        code_evidence="no_write_path",
        measured=SeedMeasurement("text", 0, 0, 0, 21, 21),
        reason="表和列在，railway-biz 没有写入路径",
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_address.id",
        child=f"{MTP}.cs_dsly_line_route.address_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 264, 264, 255, 951, 951),
        reason="保存路线后新建地址并把返回主键回填；UAT 历史数据有少量地址复用",
        sites=(
            SeedSite(
                kind="fresh_key_per_row",
                file=_LINE_ROUTE_ADMIN,
                method="saveRouteRailway",
                snippet=(
                    "AddressAdminQuery addressAdminQuery = remoteAdminService.saveOrEditAddress(address);\n"
                    "        route.setAddressId(addressAdminQuery.getId());\n"
                    "        dao.saveOrUpdate(route);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_address.id",
        child=f"{MTP}.cs_dsly_line_route_inquiry.address_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 6, 6, 6, 951, 951),
        reason="每次保存线路询价都会保存对应地址并回填新地址主键",
        sites=(
            SeedSite(
                kind="fresh_key_per_row",
                file=_LINE_ROUTE_INQUIRY_ADMIN,
                method="save",
                snippet=(
                    "AddressAdminQuery data = remoteAdminService.saveOrEditAddress(addressItem);\n"
                    "        if (ObjectUtil.isNotEmpty(data)) {\n"
                    "            item.setAddressId(data.getId());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_address.id",
        child=f"{MTP}.cs_dsly_line_route_product.address_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 135, 135, 135, 951, 951),
        reason="线路产品保存地址后，仅在产品尚无地址时回填该主键",
        sites=(
            SeedSite(
                kind="fresh_key_per_row",
                file=_LINE_ROUTE_PRODUCT_ADMIN,
                method="saveOrUpdateInfo",
                snippet=(
                    "AddressAdminQuery addressData = remoteAdminService.saveOrEditAddress(addressItem);\n"
                    "\n"
                    "        // 处理产品\n"
                    "        if (ObjectUtil.isEmpty(routeProductItem.getAddressId())) {\n"
                    "            routeProductItem.setAddressId(addressData.getId());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_address.id",
        child=f"{MTP}.cs_dsly_order_entrusted_order.address_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 89, 89, 89, 951, 951),
        reason="新增委托单时保存一条来源地址，并把返回主键回填委托单",
        sites=(
            SeedSite(
                kind="fresh_key_per_row",
                file=_ENTRUSTED_ORDER_ADMIN,
                method="save",
                snippet=(
                    "AddressAdminQuery addressAdminQuery = remoteAdminService.addressSaveOrEdit(addressAdminItem);\n"
                    "        // 新增时关联地址ID\n"
                    "        if (isAdd) {\n"
                    "            entrustedOrder.setAddressId(addressAdminQuery.getId());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_address.id",
        child=f"{MTP}.cs_dsly_order_work_plan.address_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 198, 198, 198, 951, 951),
        reason="生成作业计划时复制委托地址为新记录，再把新主键回填计划",
        sites=(
            SeedSite(
                kind="fresh_key_per_row",
                file=_ORDER_ENTRUSTED_ADMIN,
                method="generatePlanFromContract",
                snippet=(
                    "AddressAdminQuery newAddress = remoteAdminService.addressSaveOrEdit(addressAdminItem);\n"
                    "                    workPlan.setAddressId(newAddress.getId());\n"
                    "                    workPlanAdminService.update(workPlan);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_address.id",
        child=f"{MTP}.cs_dsly_railway_carrier_order.address_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 31, 31, 31, 951, 951),
        reason="每张铁路承运单构建并保存自己的地址，随后回填返回主键",
        sites=(
            SeedSite(
                kind="fresh_key_per_row",
                file=_RW_CARRIER_ADMIN,
                method="batchCreateCarrierOrder",
                snippet=(
                    "Long addressId = remoteAdminService.saveAddress(addressAdminItem);\n"
                    "            carrierOrder.setAddressId(addressId);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_address.id",
        child=f"{MTP}.cs_dsly_railway_daily_plan.address_id",
        code_cardinality="unknown",
        code_evidence="no_write_path",
        measured=SeedMeasurement("numeric", 0, 0, 0, 951, 951),
        reason="日计划表声明了 address_id，但当前构建与绑定路径均未赋值，UAT 也尚无行",
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_address.id",
        child=f"{MTP}.cs_dsly_railway_dispatch_order.address_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 21, 21, 20, 951, 951),
        reason="铁路派车单复用承运单已有地址，同一地址可被多张派车单引用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_RW_CARRIER_BASIC,
                method="buildDispatchOrder",
                snippet="dispatchOrder.setAddressId(carrierOrder.getAddressId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_address.id",
        child=f"{MTP}.cs_dsly_shipping_carrier_order.address_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 0, 0, 0, 951, 951),
        reason="海运承运单保存自己的地址并回填主键；UAT 尚无承运单",
        sites=(
            SeedSite(
                kind="fresh_key_per_row",
                file=_SHIPPING_ADMIN,
                method="batchCreateCarrierOrder",
                snippet=(
                    "Long addressId = remoteAdminService.saveAddress(addressAdminItem);\n"
                    "            carrierOrder.setAddressId(addressId);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_address.id",
        child=f"{MTP}.cs_dsly_shipping_dispatch_order.address_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 951, 951),
        reason="海运派车单复制承运单地址主键，同一地址允许被多次派车复用；UAT 尚无行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SHIPPING_PORTAL,
                method="buildDispatchOrder",
                snippet="dispatchOrder.setAddressId(carrierOrder.getAddressId());",
            ),
        ),
    ),
    # ---- Remaining shipping edges. Domain still empty in UAT; code still answers.
    # cargo_id is overloaded (basic_cargo vs carrier shipping_cargo.id) — no edge.
    SeedEdge(
        parent=f"{MTP}.cs_dsly_shipping_carrier_order.carrier_order_no",
        child=f"{MTP}.cs_dsly_shipping_dispatch_order.carrier_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 0, 0),
        reason="一张承运单可以拆成多次派车；水路未投产，数据无从验证",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SHIPPING_PORTAL,
                method="buildDispatchOrder",
                snippet="dispatchOrder.setCarrierOrderNo(carrierOrder.getCarrierOrderNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_shipping_dispatch_order.dispatch_order_no",
        child=f"{MTP}.cs_dsly_shipping_cargo.dispatch_order_no",
        code_cardinality="one_to_one",
        code_evidence="enforced",
        measured=SeedMeasurement("text", 0, 0, 0, 0, 0),
        reason="派车单号循环内新生成，一号一货；读侧 toMap 与公路同构，UAT 尚无行",
        sites=(
            SeedSite(
                kind="fresh_key_per_row",
                file=_SHIPPING_PORTAL,
                method="handleCreateDispatch",
                snippet=(
                    "String dispatchOrderNo = SequenceClient.getSingle("
                    "ShippingOrderNoEnum.DISPATCH_ORDER_NO.getCode());"
                ),
            ),
            SeedSite(
                kind="strict_to_map",
                file=_SHIPPING_PORTAL,
                method="getDispatchOrderVOList",
                snippet=(
                    "Map<String, ShippingCargoQuery> cargoMap = cargoList.stream().collect("
                    "Collectors.toMap(ShippingCargoQuery::getDispatchOrderNo, Function.identity()));"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo_category.id",
        child=f"{MTP}.cs_dsly_shipping_cargo.category_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 8, 8),
        reason="品类取自货物主数据，可被多行复用；UAT 尚无水路货",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SHIPPING_ADMIN,
                method="buildCarrierCargo",
                snippet="cargo.setCategoryId(cargoAdminQuery.getCategoryId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_shipping_carrier_order.carrier_order_no",
        child=f"{MTP}.cs_dsly_shipping_carrier_settlement.shipping_carrier_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 0, 0),
        reason="结算按入参承运单号生成，代码挡不住第二条；UAT 尚无行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SHIPPING_ADMIN,
                method="buildSettlement",
                snippet="shippingCarrierSettlementQuery.setShippingCarrierNo(carrierOrderNo);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted_order.entrusted_order_no",
        child=f"{MTP}.cs_dsly_shipping_carrier_order.entrusted_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 89, 89),
        reason="委托单号从拆段入参拷到承运单，同一委托可拆多张；UAT 尚无水路承运单",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SHIPPING_ADMIN,
                method="batchCreateCarrierOrder",
                snippet=(
                    "ShippingCarrierOrder carrierOrder = GenericBeanConverter.convert("
                    "shippingCarrierOrderAdminChildItem,ShippingCarrierOrder.class);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route.route_no",
        child=f"{MTP}.cs_dsly_shipping_carrier_order.route_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 259, 259),
        reason="路线编号取自拆段入参既有主数据，可被多张承运单复用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SHIPPING_ADMIN,
                method="batchCreateCarrierOrder",
                snippet="carrierOrder.setRouteNo(shippingCarrierOrderAdminChildItem.getRouteNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_shipping_dispatch_order.dispatch_order_no",
        child=f"{MTP}.cs_dsly_shipping_dispatch_record.dispatch_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 0, 0),
        reason="装货/卸货/签收等节点各记一条轨迹；UAT 尚无行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SHIPPING_RECORD_BASE,
                method="buildRouteItem",
                snippet="record.setDispatchOrderNo(dispatchOrderNo);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_shipping_dispatch_order.id",
        child=f"{MTP}.cs_dsly_shipping_dispatch_manifest.dispatch_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="货票可按运单主键保存多行；UAT 尚无行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SHIPPING_MANIFEST_ADMIN_CONTROLLER,
                method="save",
                snippet=(
                    "ShippingDispatchManifest dispatchManifest = GenericBeanConverter.convert(\n"
                    "                dispatchManifestAdminItem, ShippingDispatchManifest.class);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo.id",
        child=f"{MTP}.cs_dsly_shipping_dispatch_manifest.cargo_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 48, 48),
        reason="舱单货物由基础货物选择接口提供，同一货物可被多条舱单复用；UAT 尚无行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SHIPPING_MANIFEST_ADMIN_CONTROLLER,
                method="save",
                snippet=(
                    "ShippingDispatchManifest dispatchManifest = GenericBeanConverter.convert(\n"
                    "                dispatchManifestAdminItem, ShippingDispatchManifest.class);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo_category.id",
        child=f"{MTP}.cs_dsly_shipping_dispatch_manifest.category_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 8, 8),
        reason="舱单品类由基础品类选择接口提供，同一品类可被多条舱单复用；UAT 尚无行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SHIPPING_MANIFEST_ADMIN_CONTROLLER,
                method="save",
                snippet=(
                    "ShippingDispatchManifest dispatchManifest = GenericBeanConverter.convert(\n"
                    "                dispatchManifestAdminItem, ShippingDispatchManifest.class);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo_category.id",
        child=f"{MTP}.cs_dsly_basic_cargo.category_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 48, 29, 6, 8, 8),
        reason="货物大类来自入参，多个货物可挂同一大类；UAT 29 行 6 个键",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_CARGO_ADMIN,
                method="saveFromMasterGoods",
                snippet="cargoItem.setCategoryId(item.getCategoryId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo.id",
        child=f"{MTP}.cs_dsly_basic_site_fee_item.cargo_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 48, 48),
        reason="站点费用按货物名称解析成 cargo.id，同一货物可配多项；UAT 费用表为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SITE_FEE_ADMIN,
                method="validateSiteFeeData",
                snippet="siteFeeCargoAdminItem.setCargoId(cargoQuery.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_site_fee_item.id",
        child=f"{MTP}.cs_dsly_basic_site_fee_item_range.item_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="一个收费项目挂多个阶梯区间，itemId 在内层循环共用；UAT 无行",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_SITE_FEE_ADMIN,
                method="save",
                snippet="siteFeeItemRange.setItemId(siteFeeCargoAdminItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_site_fee_item.id",
        child=f"{MTP}.cs_dsly_basic_site_fee_item_business.basic_site_fee_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="保存时每个收费项目写一行业务配置，没有挡住第二次；UAT 无行",
        sites=(
            SeedSite(
                kind="single_write",
                file=_SITE_FEE_ADMIN,
                method="save",
                snippet="siteFeeBusinessAdminItem.setBasicSiteFeeId(siteFeeCargoAdminItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_billing_template.id",
        child=f"{MTP}.cs_dsly_basic_business_info.template_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="复制模板时多条业务挂到新模板 id；UAT 模板和业务均为空",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_TEMPLATE_ADMIN,
                method="copyAdd",
                snippet="formerBusiness.setTemplateId(copyTemplate.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_expense_config.expense_code",
        child=f"{MTP}.cs_dsly_basic_business_info.expense_code",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 7, 7),
        reason="业务行费用代码从入参拷贝，同一费用可配多条业务；UAT 业务表为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BUSINESS_ADMIN,
                method="save",
                snippet="saveOrUpdate(business);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo_category.category_code",
        child=f"{MTP}.cs_dsly_basic_business_info.category_code",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 8, 8),
        reason="业务行大类代码从入参拷贝，没有 category_id；UAT 业务表为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BUSINESS_ADMIN,
                method="save",
                snippet="saveOrUpdate(business);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo_category.id",
        child=f"{MTP}.cs_dsly_basic_cargo_base_price_config.cargo_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 10, 10, 5, 8, 8),
        reason="基础价配置界面明确按货物大类选择 cargo_id；UAT 10 行 5 个键均能匹配大类",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_PRICE_EDIT,
                method="template",
                snippet='type="cargoCategoryByIdConfig"',
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo.id",
        child=f"{MTP}.cs_dsly_basic_cargo_external.cargo_id",
        code_cardinality="unknown",
        code_evidence="no_write_path",
        measured=SeedMeasurement("numeric", 0, 0, 0, 48, 48),
        reason="实体字段注释明确关联基础货物，但当前代码没有 CargoExternal 持久化入口，UAT 也无行",
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_expense_config.expense_code",
        child=f"{MTP}.cs_dsly_basic_expense_config.related_expense_code",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 14, 10, 3, 14, 14, orphan_keys=2),
        reason="关联费用代码随配置入参保存；UAT 含空串和无匹配代码，当前有 2 个孤儿键",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_EXPENSE_ADMIN,
                method="save",
                snippet=(
                    "ExpenseConfig expenseConfig = GenericBeanConverter.convert("
                    "expenseConfigAdminItem, ExpenseConfig.class);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route.id",
        child=f"{MTP}.cs_dsly_line_route_product_relate.route_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 240, 240, 236, 259, 259),
        reason="产品绑定循环写入入参线路 id，同一线路可挂到多个产品",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_LINE_PRODUCT_RELATE_ADMIN,
                method="relateRouteProduct",
                snippet="routeProductRelate.setRouteId(route.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route_product.id",
        child=f"{MTP}.cs_dsly_line_route_product_relate.route_product_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 240, 240, 133, 133, 133),
        reason="一次绑定把产品 id 写到该产品下的每一条线路关系",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_LINE_PRODUCT_RELATE_ADMIN,
                method="relateRouteProduct",
                snippet="routeProductRelate.setRouteProductId(routeProductItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route.id",
        child=f"{MTP}.cs_dsly_line_route_relate.route_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 49, 49, 49, 259, 259),
        reason="智能组合新线路可挂多条关联原线；UAT 目前一条新线路只挂一条",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_LINE_ROUTE_ADMIN,
                method="batchSaveRouteRailway",
                snippet="routeRelateItem.setRouteId(newRouteId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route.id",
        child=f"{MTP}.cs_dsly_line_route_relate.original_route_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 49, 49, 8, 259, 259),
        reason="原线路快照 id 来自入参关联线，同一快照可被多条组合线引用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_LINE_ROUTE_ADMIN,
                method="batchSaveRouteRailway",
                snippet="routeRelateItem.setOriginalRouteId(snapshotId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route.id",
        child=f"{MTP}.cs_dsly_line_route_railway.route_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 69, 69, 69, 259, 259),
        reason="铁路线路扩展一行对应一条线路，saveOrUpdate 按 routeId 回写",
        sites=(
            SeedSite(
                kind="single_write",
                file=_LINE_ROUTE_ADMIN,
                method="saveRouteRailway",
                snippet="routeRailway.setRouteId(routeId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route.id",
        child=f"{MTP}.cs_dsly_line_route_railway_station.route_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 175, 175, 69, 259, 259),
        reason="一条铁路线保存时循环把同一 routeId 写到沿途每个站点",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_LINE_ROUTE_ADMIN,
                method="saveRouteRailway",
                snippet=(
                    "for (RouteRailwayStationItem routeRailwayStationItem : routeRailwayStationList) {\n"
                    "            routeRailwayStationItem.setRouteId(route.getId());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_station.id",
        child=f"{MTP}.cs_dsly_line_route_railway_station.station_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 175, 175, 9, 22, 22),
        reason="站点 id 取自入参站点列表，同一站点可出现在多条铁路线上",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_LINE_ROUTE_ADMIN,
                method="batchSaveRouteRailway",
                snippet="routeRailwayStation.setStationId(stationQuery.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route.id",
        child=f"{MTP}.cs_dsly_line_route_cargo_charge.route_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 260, 260, 259, 259, 259),
        reason="保存线路时循环把同一线路 id 写到每条货物报价",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_LINE_ROUTE_ADMIN,
                method="save",
                snippet="routeCargo.setRouteId(routeItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo.id",
        child=f"{MTP}.cs_dsly_line_route_cargo_charge.cargo_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 260, 258, 4, 48, 48, orphan_keys=4),
        reason="导入按货物名称回填 cargoId，同一货物可出现在多条线路报价；UAT 有 4 个孤儿键",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_LINE_ROUTE_ADMIN,
                method="validateImportData",
                snippet="routeCargoCharge.setCargoId(cargoQuery.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_expense_config.expense_code",
        child=f"{MTP}.cs_dsly_line_route_cargo_charge.expense_code",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 260, 260, 5, 7, 7, orphan_keys=2),
        reason="费用代码随报价入参转换保存，同一费用可配多条线路报价；UAT 有 2 个孤儿键",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_LINE_CARGO_CHARGE_ADMIN_CTRL,
                method="save",
                snippet=(
                    "RouteCargoCharge routeCargoCharge = GenericBeanConverter.convert("
                    "routeCargoChargeItem, RouteCargoCharge.class);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route.id",
        child=f"{MTP}.cs_dsly_line_route_cargo_charge_range.route_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 261, 261, 259, 259, 259),
        reason="阶梯报价循环复用当前线路 id",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_LINE_ROUTE_ADMIN,
                method="save",
                snippet="routeCargoChargeRange.setRouteId(routeItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route_cargo_charge.id",
        child=f"{MTP}.cs_dsly_line_route_cargo_charge_range.charge_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 261, 261, 259, 260, 260),
        reason="一条货物报价保存后把主键回填到其全部阶梯行",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_LINE_ROUTE_ADMIN,
                method="save",
                snippet="routeCargoChargeRange.setChargeId(routeCargo.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route_inquiry.id",
        child=f"{MTP}.cs_dsly_line_route_inquiry_quote_plan.inquiry_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 1, 1, 1, 6, 6),
        reason="询价 id 从方案入参拷贝，同一询价可有多份承运商报价方案；UAT 仅 1 行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_LINE_QUOTE_PLAN_ADMIN,
                method="saveInquiryQuoteRoute",
                snippet=(
                    "BeanUtil.copyProperties(item, routeInquiryQuotePlan);\n"
                    "        dao.saveOrUpdate(routeInquiryQuotePlan);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route_product.id",
        child=f"{MTP}.cs_dsly_line_route_inquiry_quote_plan.route_product_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 1, 1, 1, 133, 133),
        reason="保存报价方案时把刚生成的线路产品主键写到方案上",
        sites=(
            SeedSite(
                kind="single_write",
                file=_LINE_QUOTE_PLAN_ADMIN,
                method="saveInquiryQuoteRoute",
                snippet="item.setRouteProductId(routeProductAdminItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_approval_user.id",
        child=f"{MTP}.cs_dsly_line_route.approval_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 259, 206, 24, 46, 46),
        reason="发起审核后把审批单 id 回写线路，同一审批单可挂多条线路",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_LINE_ROUTE_ADMIN,
                method="recordAuditRecord",
                snippet="route.setApprovalId(approvalUserAdminItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_approval_user.id",
        child=f"{MTP}.cs_dsly_line_route_product.approval_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 133, 131, 16, 46, 46),
        reason="产品审核同样回写审批单 id，同一审批单可挂多个产品",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_LINE_ROUTE_PRODUCT_ADMIN,
                method="recordAuditRecord",
                snippet="route.setApprovalId(approvalUserAdminItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route_product.id",
        child=f"{MTP}.cs_dsly_line_route_product.parent_route_product_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 133, 107, 16, 133, 133, orphan_keys=1),
        reason="复制产品时把源产品 id 写成父产品，同一源产品可复制多次；UAT 有 1 个孤儿键",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_LINE_ROUTE_PRODUCT_BASIC,
                method="copyRouteProduct",
                snippet="routeProductItem.setParentRouteProductId(routeProductItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route.route_no",
        child=f"{MTP}.cs_dsly_order_entrusted_order_relate.route_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 138, 138, 127, 259, 259),
        reason="委托订单拆分时把所选线路编号写入关联行；UAT 138 行全部命中线路",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ENTRUSTED_ORDER_ADMIN,
                method="createEntrustedOrderRelate",
                snippet="entrustedOrderRelate.setRouteNo(entrustedOrderSplitAdminQuery.getRouteNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted.entrusted_no",
        child=f"{MTP}.cs_dsly_line_route_inquiry.entrusted_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 6, 4, 1, 118, 118, orphan_keys=1),
        reason="询价编辑页从委托需求列表选择 entrustedNo；UAT 当前 1 个键找不到存活委托需求",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_LINE_ROUTE_INQUIRY_EDIT,
                method="selectEntrustedNoChange",
                snippet="formData.value.entrustedNo = val.entrustedNo;",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route.id",
        child=f"{MTP}.cs_dsly_line_route.parent_route_id",
        code_cardinality="unknown",
        code_evidence="no_write_path",
        measured=SeedMeasurement("numeric", 259, 0, 0, 259, 259),
        reason="线路实体声明父线路字段，但业务入参和保存路径均未赋值，UAT 259 行全空",
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_port.id",
        child=f"{MTP}.cs_dsly_operation_entrusted.port_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="门户按港口名称查出港口后写入 portId；UAT 委托需求与港口表均为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_ENTRUSTED_PORTAL,
                method="savePortal",
                snippet="saveItem.setPortId(query.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted_quote.id",
        child=f"{MTP}.cs_dsly_operation_entrusted.quote_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="报价保存后把当次报价主键回填到委托需求；UAT 两侧均为空",
        sites=(
            SeedSite(
                kind="single_write",
                file=_OP_ENTRUSTED_ADMIN,
                method="quoteAdmin",
                snippet="entrusted.setQuoteId(quoteSaveItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted.id",
        child=f"{MTP}.cs_dsly_operation_entrusted_quote.entrusted_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="每次报价挂同一委托需求，可多次再报；UAT 报价表为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_ENTRUSTED_ADMIN,
                method="quoteAdmin",
                snippet="quoteSaveItem.setEntrustedId(entrusted.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted.id",
        child=f"{MTP}.cs_dsly_operation_entrusted_business_type.entrusted_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="保存委托需求时循环把同一需求主键写入多条业务类型；UAT 业务类型表为空",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_OP_ENTRUSTED_PORTAL,
                method="savePortal",
                snippet="entrustedBusinessType.setEntrustedId(entrusted.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted_business_type.id",
        child=f"{MTP}.cs_dsly_operation_entrusted_business_cargo.business_type_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="业务类型保存后把主键写回该类型下全部货物行；UAT 业务货物表为空",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_OP_ENTRUSTED_PORTAL,
                method="savePortal",
                snippet="entrustedBusinessCargoItem.setBusinessTypeId(entrustedBusinessTypeItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo_category.category_code",
        child=f"{MTP}.cs_dsly_operation_entrusted_business_cargo.category_code",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 6, 6),
        reason="业务货物行从入参拷贝货物类型编码；UAT 货物行空，大类存活 6 个编码",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_ENTRUSTED_ADMIN,
                method="saveOrUpdateEntrusted",
                snippet=(
                    "List<EntrustedBusinessCargo> list = Convert.toList("
                    "EntrustedBusinessCargo.class, entrustedBusinessCargoInsertList);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted_business_type.id",
        child=f"{MTP}.cs_dsly_operation_entrusted_business_container.business_type_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="业务类型保存后把主键写回该类型下全部集装箱行；UAT 业务箱表为空",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_OP_ENTRUSTED_PORTAL,
                method="savePortal",
                snippet="businessContainerItem.setBusinessTypeId(entrustedBusinessTypeItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo.cargo_code",
        child=f"{MTP}.cs_dsly_operation_entrusted_business_cargo.main_cargo_code",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 48, 48),
        reason="委托业务货物选择基础货物时把 cargoCode 写入 mainCargoCode；UAT 业务货物表为空，基础货物有 48 个存活编码",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_ENTRUSTED_EDIT,
                method="handleCargoChange",
                snippet='"mainCargoCode":r.cargoCode,',
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted.id",
        child=f"{MTP}.cs_dsly_operation_entrusted_order.operation_entrusted_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="从委托需求创建港口委托订单时写入需求主键；UAT 订单表为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_ENTRUSTED_BASIC,
                method="createOrder",
                snippet="orderItem.setOperationEntrustedId(entrusted.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted.operation_entrusted_no",
        child=f"{MTP}.cs_dsly_operation_entrusted_order.operation_entrusted_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 0, 0),
        reason="创建港口委托订单时同步拷贝需求单号；UAT 订单表为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_ENTRUSTED_BASIC,
                method="createOrder",
                snippet="orderItem.setOperationEntrustedNo(entrusted.getOperationEntrustedNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_port.id",
        child=f"{MTP}.cs_dsly_operation_entrusted_order.port_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="创建港口委托订单时拷贝需求上的港口主键；UAT 订单与港口表均为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_ENTRUSTED_BASIC,
                method="createOrder",
                snippet="orderItem.setPortId(entrusted.getPortId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted_quote.id",
        child=f"{MTP}.cs_dsly_operation_entrusted_quote_info.quote_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="报价明细循环共用刚保存的报价主键；UAT 报价明细表为空",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_OP_ENTRUSTED_ADMIN,
                method="quoteAdmin",
                snippet="entrustedQuoteInfoAdminItem.setQuoteId(quoteSaveItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo.id",
        child=f"{MTP}.cs_dsly_operation_entrusted_order.cargo_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 48, 48),
        reason="创建委托订单的入参包含基础货物 cargoId，并通过 Bean 转换落到订单 cargo_id；UAT 订单表为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_ENTRUSTED_BASIC,
                method="createOrder",
                snippet=(
                    "OperationEntrustedOrderItem orderItem = "
                    "BeanUtil.toBean(item, OperationEntrustedOrderItem.class);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_port.id",
        child=f"{MTP}.cs_dsly_operation_entrusted_quote_info.port_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="报价明细循环共用委托需求上的港口主键；UAT 明细与港口表均为空",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_OP_ENTRUSTED_ADMIN,
                method="quoteAdmin",
                snippet="entrustedQuoteInfoAdminItem.setPortId(entrusted.getPortId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted_order.id",
        child=f"{MTP}.cs_dsly_operation_appointment.entrusted_order_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="预约保存时按入参委托订单主键查单并落库；UAT 预约表为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_APPOINTMENT_BASIC,
                method="save",
                snippet="Long entrustedOrderId = item.getEntrustedOrderId();",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_port.id",
        child=f"{MTP}.cs_dsly_operation_appointment.port_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="预约保存时从委托订单拷贝港口主键；UAT 预约与港口表均为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_APPOINTMENT_BASIC,
                method="save",
                snippet="item.setPortId(entrustedOrder.getPortId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted_order.operation_entrusted_no",
        child=f"{MTP}.cs_dsly_operation_appointment.operation_entrusted_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 0, 0),
        reason="预约保存时从委托订单同步拷贝委托需求号；UAT 两侧均为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_APPOINTMENT_BASIC,
                method="save",
                snippet="item.setOperationEntrustedNo(entrustedOrder.getOperationEntrustedNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted_order.operation_entrusted_order_no",
        child=f"{MTP}.cs_dsly_operation_appointment.operation_entrusted_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 0, 0),
        reason="预约保存时从委托订单同步拷贝委托订单号；UAT 两侧均为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_APPOINTMENT_BASIC,
                method="save",
                snippet=(
                    "item.setOperationEntrustedOrderNo("
                    "entrustedOrder.getOperationEntrustedOrderNo());"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_appointment.id",
        child=f"{MTP}.cs_dsly_operation_appointment_vehicle.appointment_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="预约车辆从入参转换后整行保存，appointmentId 来自调用方；UAT 车辆表为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_VEHICLE,
                method="save",
                snippet="AppointmentVehicle appointmentVehicle = GenericBeanConverter.convert(item, AppointmentVehicle.class);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted_order.id",
        child=f"{MTP}.cs_dsly_operation_container.entrusted_order_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="作业集装箱从入参转换后保存，entrustedOrderId 来自调用方；UAT 集装箱表为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_CONTAINER_BASIC,
                method="save",
                snippet="OperationContainer container = GenericBeanConverter.convert(item, OperationContainer.class);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted_order.operation_entrusted_order_no",
        child=f"{MTP}.cs_dsly_operation_pick_up_appointment.entrust_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 0, 0),
        reason="提货预约的 entrustOrderNo 字段保存港口委托订单号；UAT 两侧均为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_PICKUP,
                method="save",
                snippet=(
                    "PickUpAppointment pickUpAppointment = "
                    "GenericBeanConverter.convert(item, PickUpAppointment.class);"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted_order.id",
        child=f"{MTP}.cs_dsly_operation_general_cargo.entrusted_order_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="散杂货从入参转换后保存，entrustedOrderId 来自调用方；UAT 散杂货表为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_OP_GENERAL_CARGO_BASIC,
                method="save",
                snippet="GeneralCargo generalCargo = GenericBeanConverter.convert(item, GeneralCargo.class);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_operation_entrusted_order.id",
        child=f"{MTP}.cs_dsly_operation_work_node.entrusted_order_id",
        code_cardinality="one_to_one",
        code_evidence="enforced",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="新增作业节点时若该委托订单已有节点则抛错；UAT 作业节点表为空",
        sites=(
            SeedSite(
                kind="unique_guard",
                file=_OP_WORKNODE_BASIC,
                method="save",
                snippet=(
                    "WorkNode workNode = dao.findFirst(new ConditionRule()"
                    ".andEqual(WorkNode::getEntrustedOrderId, item.getEntrustedOrderId()));\n"
                    "            if (ObjectUtil.isNotEmpty(workNode)) {\n"
                    '                throw new BusinessException("该委托订单已经存在作业节点，不可重复新增");\n'
                    "            }"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted.id",
        child=f"{MTP}.cs_dsly_order_entrusted_order.entrusted_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 89, 89, 86, 118, 118),
        reason="作业计划下发委托订单时写入需求主键，同一需求可拆多张订单",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_WORK_PLAN_ADMIN,
                method="createEntrustedOrder",
                snippet="entrustedOrderItem.setEntrustedId(entrustedQuery.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted.id",
        child=f"{MTP}.cs_dsly_order_entrusted_quote.entrusted_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 118, 118, 109, 118, 118),
        reason="报价方案挂同一委托需求，驳回后可再报",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_QUOTE_ADMIN,
                method="saveQuote",
                snippet="entrustedQuoteSaveItem.setEntrustedId(entrusted.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted_quote.id",
        child=f"{MTP}.cs_dsly_order_entrusted.quote_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 118, 109, 109, 118, 118),
        reason="报价保存后把当次报价主键回填到委托需求",
        sites=(
            SeedSite(
                kind="single_write",
                file=_ORDER_QUOTE_ADMIN,
                method="saveQuote",
                snippet="entrusted.setQuoteId(quote.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route_product.route_product_no",
        child=f"{MTP}.cs_dsly_order_entrusted.route_product_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 118, 115, 16, 136, 136, orphan_keys=1),
        reason="委托需求保存所选线路产品编号，同一产品可被多条需求复用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_QUOTE_ADMIN,
                method="saveQuote",
                snippet="entrusted.setRouteProductNo(routeProduct.getRouteProductNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route_product.route_product_no",
        child=f"{MTP}.cs_dsly_order_entrusted_quote.route_product_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 118, 118, 76, 136, 136),
        reason="报价时把所选线路产品编号写入报价行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_QUOTE_ADMIN,
                method="saveQuote",
                snippet="entrustedQuoteSaveItem.setRouteProductNo(routeProduct.getRouteProductNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_line_route_product.route_product_no",
        child=f"{MTP}.cs_dsly_order_entrusted_order.route_product_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 89, 89, 15, 135, 135, orphan_keys=1),
        reason="下发委托订单时从需求拷贝线路产品编号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_WORK_PLAN_ADMIN,
                method="createEntrustedOrder",
                snippet="entrustedOrderItem.setRouteProductNo(entrustedQuery.getRouteProductNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_address.id",
        child=f"{MTP}.cs_dsly_order_entrusted.entrusted_address_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 118, 118, 118, 960, 960),
        reason="保存委托需求时把地址服务返回的主键回填 entrustedAddressId",
        sites=(
            SeedSite(
                kind="single_write",
                file=_ORDER_ENTRUSTED_ADMIN,
                method="saveOrUpdateEntrusted",
                snippet="converted.setEntrustedAddressId(addressId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted.id",
        child=f"{MTP}.cs_dsly_order_work_plan.entrusted_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 193, 193, 97, 118, 118),
        reason="合同转作业计划时挂委托需求，总单拆子单后仍共用同一需求",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_ENTRUSTED_ADMIN,
                method="generatePlanFromContract",
                snippet="workPlan.setEntrustedId(item.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted.entrusted_no",
        child=f"{MTP}.cs_dsly_order_work_plan.entrusted_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 193, 193, 97, 118, 118),
        reason="作业计划同步拷贝委托需求号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_ENTRUSTED_ADMIN,
                method="generatePlanFromContract",
                snippet="workPlan.setEntrustedNo(lockedEntrusted.getEntrustedNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted_order.id",
        child=f"{MTP}.cs_dsly_order_work_plan.entrusted_order_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 200, 88, 88, 89, 89),
        reason="作业计划受理生成委托订单后回填计划上的订单主键",
        sites=(
            SeedSite(
                kind="single_write",
                file=_ORDER_WORK_PLAN_ADMIN,
                method="save",
                snippet="workPlan.setEntrustedOrderId(entrustedOrder.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_work_plan.id",
        child=f"{MTP}.cs_dsly_order_work_plan.parent_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 200, 94, 89, 191, 191),
        reason="作业计划下发子单时把总单主键写入 parentId，一个总单可拆多条子单",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_WORK_PLAN_PORTAL,
                method="createSubPlan",
                snippet="subPlan.setParentId(condition.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo.id",
        child=f"{MTP}.cs_dsly_order_entrusted_cargo.cargo_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 219, 219, 31, 48, 48),
        reason="委托货物从入参选择货物主数据，同一货物可被多行复用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_ENTRUSTED_ADMIN,
                method="saveOrUpdateEntrusted",
                snippet="entrustedCargoItem.setCargoId(item.getCargoId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo_category.id",
        child=f"{MTP}.cs_dsly_order_entrusted_cargo.category_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 219, 216, 6, 6, 6),
        reason="委托货物同时写入货物大类主键",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_ENTRUSTED_ADMIN,
                method="saveOrUpdateEntrusted",
                snippet="entrustedCargoItem.setCategoryId(item.getCategoryId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted_order.id",
        child=f"{MTP}.cs_dsly_order_node.source_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 238, 238, 89, 89, 89),
        reason="运输跟踪节点始终挂委托订单主键，一单多个状态节点",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ENTRUSTED_ORDER_ADMIN,
                method="saveOrderNode",
                snippet="orderNode.setSourceId(orderId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted_order.id",
        child=f"{MTP}.cs_dsly_order_booking_application.entrusted_order_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 3, 3, 3, 89, 89),
        reason="委托订单生成后自动创建订舱申请并写入订单主键",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_BOOKING_BASIC,
                method="generateBookingData",
                snippet="bookingApplication.setEntrustedOrderId(item.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted_order.entrusted_order_no",
        child=f"{MTP}.cs_dsly_order_booking_application.entrusted_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 3, 3, 3, 89, 89),
        reason="订舱申请同步拷贝委托订单号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_BOOKING_BASIC,
                method="generateBookingData",
                snippet="bookingApplication.setEntrustedOrderNo(item.getEntrustedOrderNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_booking_application.id",
        child=f"{MTP}.cs_dsly_order_booking_application_confirm.booking_application_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 1, 1, 1, 3, 3),
        reason="订舱确认保存时挂订舱申请主键",
        sites=(
            SeedSite(
                kind="single_write",
                file=_ORDER_CONFIRM_ADMIN,
                method="saveOrUpdateInfo",
                snippet="this.saveOrUpdate(item);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_outbound_order.id",
        child=f"{MTP}.cs_dsly_order_outbound_order_detail.outbound_order_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 46, 46, 18, 28, 28),
        reason="WMS 出库明细循环挂同一出库主单主键",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_ORDER_WMS,
                method="fillDetail",
                snippet="detail.setOutboundOrderId(outboundOrder.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_outbound_order.outbound_order_no",
        child=f"{MTP}.cs_dsly_order_outbound_order_detail.outbound_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 46, 46, 18, 28, 28),
        reason="出库明细同时写下出库单号",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_ORDER_WMS,
                method="fillDetail",
                snippet="detail.setOutboundOrderNo(outboundOrder.getOutboundOrderNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo.id",
        child=f"{MTP}.cs_dsly_order_outbound_order_detail.cargo_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 46, 46, 14, 48, 48),
        reason="出库明细按 SKU 匹配货物主数据",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_WMS,
                method="fillDetail",
                snippet="detail.setCargoId(cargo.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_outbound_order.id",
        child=f"{MTP}.cs_dsly_order_outbound_entrusted_relation.outbound_order_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 59, 59, 28, 28, 28),
        reason="出库单按商品生成多条委托需求关联",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_WMS,
                method="saveEntrustedRelation",
                snippet="relation.setOutboundOrderId(outboundOrder.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted.id",
        child=f"{MTP}.cs_dsly_order_outbound_entrusted_relation.entrusted_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 59, 59, 59, 118, 118, orphan_keys=10),
        reason="每条出库关联对应一条生成的委托需求；UAT 有 10 个键找不到存活需求",
        sites=(
            SeedSite(
                kind="single_write",
                file=_ORDER_WMS,
                method="saveEntrustedRelation",
                snippet="relation.setEntrustedId(entrusted.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_outbound_order.id",
        child=f"{MTP}.cs_dsly_order_outbound_transport_relation.outbound_order_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 22, 22, 8, 28, 28),
        reason="装货履约关系从明细拷出库主键，一单可对应多条运输",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_TRANSPORT,
                method="bindLoadedTransport",
                snippet="relation.setOutboundOrderId(detail.getOutboundOrderId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_outbound_order_detail.id",
        child=f"{MTP}.cs_dsly_order_outbound_transport_relation.outbound_detail_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 22, 22, 22, 46, 46),
        reason="履约关系按明细主键关联，代码不禁止同一明细多次装货",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_ORDER_TRANSPORT,
                method="bindLoadedTransport",
                snippet="relation.setOutboundDetailId(detail.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_route.id",
        child=f"{MTP}.cs_bt_route_station.route_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 18, 18, 5, 5, 5),
        reason="同步过程站点时循环外定好线路主键，多站共用",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_BT_ROUTE,
                method="syncRouteStations",
                snippet="station.setRouteId(routeId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_route.route_code",
        child=f"{MTP}.cs_bt_route_station.route_code",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 18, 18, 5, 5, 5),
        reason="同步过程站点时同时写下线路编号",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_BT_ROUTE,
                method="syncRouteStations",
                snippet="station.setRouteCode(routeCode);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_route.id",
        child=f"{MTP}.cs_bt_departure_plan.route_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 14, 14, 4, 5, 5),
        reason="开行计划从入参线路主键落库，一条线路可开多班",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_DEPARTURE,
                method="saveBtDeparturePlan",
                snippet="BtDeparturePlan departurePlan = Convert.convert(BtDeparturePlan.class, item);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_route.route_code",
        child=f"{MTP}.cs_bt_monthly_entrusted.route_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 25, 25, 5, 5, 5),
        reason="月度需求用班列线路编号选线，多张需求可共用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_MONTHLY,
                method="save",
                snippet="MonthlyEntrusted monthlyEntrusted = BeanUtil.toBean(item, MonthlyEntrusted.class);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_monthly_entrusted.demand_no",
        child=f"{MTP}.cs_bt_daily_plan.demand_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 27, 27, 13, 25, 25),
        reason="提报日计划时拷月度需求单号，一张需求可拆多日",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_MONTHLY,
                method="fillReportPlan",
                snippet="plan.setDemandNo(monthlyEntrusted.getDemandNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_daily_plan.id",
        child=f"{MTP}.cs_bt_daily_plan_box.daily_plan_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 85, 85, 79, 27, 27, orphan_keys=52),
        reason="箱型循环挂同一日计划主键；UAT 大量箱行指到已删日计划",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_BT_DAILY,
                method="saveBoxes",
                snippet="box.setDailyPlanId(item.getDailyPlanId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_daily_plan.daily_plan_no",
        child=f"{MTP}.cs_bt_daily_plan_box.daily_plan_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 85, 85, 79, 27, 27, orphan_keys=52),
        reason="箱型同时写下日计划编号",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_BT_DAILY,
                method="saveBoxes",
                snippet="box.setDailyPlanNo(item.getDailyPlanNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_daily_plan.id",
        child=f"{MTP}.cs_bt_waybill.daily_plan_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 19, 19, 19, 27, 27),
        reason="发运生成运单时挂日计划主键，代码允许同一日计划多次发运",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_WAYBILL,
                method="buildDispatchedWaybill",
                snippet="waybill.setDailyPlanId(plan.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_daily_plan.daily_plan_no",
        child=f"{MTP}.cs_bt_waybill.daily_plan_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 19, 19, 19, 27, 27),
        reason="运单同时写下日计划编号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_WAYBILL,
                method="buildDispatchedWaybill",
                snippet="waybill.setDailyPlanNo(plan.getDailyPlanNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_monthly_entrusted.demand_no",
        child=f"{MTP}.cs_bt_waybill.demand_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 19, 19, 12, 25, 25),
        reason="运单从日计划拷需求单号，一张需求可对应多张运单",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_WAYBILL,
                method="buildDispatchedWaybill",
                snippet="waybill.setDemandNo(plan.getDemandNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_departure_plan.id",
        child=f"{MTP}.cs_bt_waybill.departure_plan_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 19, 9, 9, 14, 14),
        reason="按开行计划发运时写入计划主键，一班可挂多个日计划运单",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_WAYBILL,
                method="createByDailyPlanDispatch",
                snippet="waybill.setDeparturePlanId(departurePlanId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_departure_plan.departure_plan_no",
        child=f"{MTP}.cs_bt_waybill.departure_plan_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 19, 9, 9, 14, 14),
        reason="运单同时写下开行计划编号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_WAYBILL,
                method="createByDailyPlanDispatch",
                snippet="waybill.setDeparturePlanNo(departurePlanNo);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_waybill.id",
        child=f"{MTP}.cs_bt_waybill_box.waybill_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 23, 23, 21, 19, 19, orphan_keys=2),
        reason="按箱型分摊时循环挂同一运单主键",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_BT_WAYBILL,
                method="saveWaybillBoxes",
                snippet="box.setWaybillId(waybill.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_waybill.waybill_no",
        child=f"{MTP}.cs_bt_waybill_box.waybill_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 23, 23, 21, 19, 19, orphan_keys=2),
        reason="运单箱同时写下运单编号",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_BT_WAYBILL,
                method="saveWaybillBoxes",
                snippet="box.setWaybillNo(waybill.getWaybillNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_daily_plan.id",
        child=f"{MTP}.cs_bt_waybill_box.daily_plan_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 23, 23, 21, 27, 27, orphan_keys=2),
        reason="运单箱从运单拷日计划主键",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_BT_WAYBILL,
                method="saveWaybillBoxes",
                snippet="box.setDailyPlanId(waybill.getDailyPlanId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_daily_plan.daily_plan_no",
        child=f"{MTP}.cs_bt_waybill_box.daily_plan_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 23, 23, 21, 27, 27, orphan_keys=2),
        reason="运单箱同时写下日计划编号",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_BT_WAYBILL,
                method="saveWaybillBoxes",
                snippet="box.setDailyPlanNo(waybill.getDailyPlanNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_waybill.id",
        child=f"{MTP}.cs_bt_waybill_voucher.waybill_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 1, 1, 1, 19, 19),
        reason="凭证循环挂同一运单主键",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_BT_WAYBILL,
                method="saveVouchers",
                snippet="voucher.setWaybillId(waybill.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_waybill.waybill_no",
        child=f"{MTP}.cs_bt_waybill_voucher.waybill_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 1, 1, 1, 19, 19),
        reason="凭证同时写下运单编号",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_BT_WAYBILL,
                method="saveVouchers",
                snippet="voucher.setWaybillNo(waybill.getWaybillNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_departure_plan.id",
        child=f"{MTP}.cs_bt_departure_plan_station.departure_plan_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 58, 58, 14, 14, 14),
        reason="同步关键站点时循环外定开行计划主键",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_BT_DEPARTURE_STATION,
                method="syncPlanStations",
                snippet="station.setDeparturePlanId(departurePlanId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_departure_plan.departure_plan_no",
        child=f"{MTP}.cs_bt_departure_plan_station.departure_plan_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 58, 58, 14, 14, 14),
        reason="关键站点同时写下开行计划编号",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_BT_DEPARTURE_STATION,
                method="syncPlanStations",
                snippet="station.setDeparturePlanNo(departurePlanNo);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_departure_plan.id",
        child=f"{MTP}.cs_bt_departure_plan_daily_plan.departure_plan_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 15, 15, 12, 14, 14),
        reason="关联日计划时写入开行计划主键，一班可关联多日",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_DEPARTURE_DAILY,
                method="fillPlanSnapshot",
                snippet="relation.setDeparturePlanId(departurePlan.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_departure_plan.departure_plan_no",
        child=f"{MTP}.cs_bt_departure_plan_daily_plan.departure_plan_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 15, 15, 12, 14, 14),
        reason="关联行同时写下开行计划编号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_DEPARTURE_DAILY,
                method="fillPlanSnapshot",
                snippet="relation.setDeparturePlanNo(departurePlan.getDeparturePlanNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_daily_plan.id",
        child=f"{MTP}.cs_bt_departure_plan_daily_plan.daily_plan_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 15, 15, 14, 27, 27, orphan_keys=1),
        reason="关联行写入日计划主键，同一日计划可被多班关联",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_DEPARTURE_DAILY,
                method="fillDailyPlanSnapshot",
                snippet="relation.setDailyPlanId(dailyPlan.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_daily_plan.daily_plan_no",
        child=f"{MTP}.cs_bt_departure_plan_daily_plan.daily_plan_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 15, 15, 14, 27, 27, orphan_keys=1),
        reason="关联行同时写下日计划编号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_DEPARTURE_DAILY,
                method="fillDailyPlanSnapshot",
                snippet="relation.setDailyPlanNo(dailyPlan.getDailyPlanNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_departure_plan.id",
        child=f"{MTP}.cs_bt_departure_plan_change_record.departure_plan_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 3, 3, 2, 14, 14),
        reason="变更记录从开行计划快照主键，一班可多次变更",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_DEPARTURE_CHANGE,
                method="fillPlanSnapshot",
                snippet="record.setDeparturePlanId(departurePlan.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_departure_plan.departure_plan_no",
        child=f"{MTP}.cs_bt_departure_plan_change_record.departure_plan_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 3, 3, 2, 14, 14),
        reason="变更记录同时写下开行计划编号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_DEPARTURE_CHANGE,
                method="fillPlanSnapshot",
                snippet="record.setDeparturePlanNo(departurePlan.getDeparturePlanNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_monthly_entrusted.id",
        child=f"{MTP}.cs_bt_monthly_entrusted_supplement.demand_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 33, 33, 18, 25, 25, orphan_keys=3),
        reason="增补单回填月度需求主键，一张需求可多次增补",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_SUPPLEMENT,
                method="fillFromMonthlyDemand",
                snippet="supplement.setDemandId(monthlyEntrusted.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_monthly_entrusted.demand_no",
        child=f"{MTP}.cs_bt_monthly_entrusted_supplement.demand_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 33, 33, 18, 25, 25, orphan_keys=3),
        reason="增补单同时写下需求编号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_SUPPLEMENT,
                method="fillFromMonthlyDemand",
                snippet="supplement.setDemandNo(monthlyEntrusted.getDemandNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_departure_plan.id",
        child=f"{MTP}.cs_bt_train_operation_tracking.departure_plan_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 3, 3, 3, 14, 14),
        reason="作业跟踪从入参拷开行计划主键，一班可有多条作业",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_TRACKING,
                method="saveBtTrainOperationTracking",
                snippet="BtTrainOperationTracking operation = Convert.convert(BtTrainOperationTracking.class, item);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_departure_plan.departure_plan_no",
        child=f"{MTP}.cs_bt_train_operation_tracking.departure_plan_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 3, 3, 3, 14, 14),
        reason="作业跟踪同时带开行计划编号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_TRACKING,
                method="saveBtTrainOperationTracking",
                snippet="BtTrainOperationTracking operation = Convert.convert(BtTrainOperationTracking.class, item);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_route.id",
        child=f"{MTP}.cs_bt_train_operation_tracking.route_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 3, 3, 3, 5, 5),
        reason="作业跟踪从入参拷线路主键",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_TRACKING,
                method="saveBtTrainOperationTracking",
                snippet="BtTrainOperationTracking operation = Convert.convert(BtTrainOperationTracking.class, item);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_departure_plan.id",
        child=f"{MTP}.cs_bt_train_operation_log.departure_plan_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 40, 40, 11, 14, 14),
        reason="作业日志从开行计划主键落库，一班多次操作",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_LOG,
                method="buildPlanLog",
                snippet="log.setDeparturePlanId(plan.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_departure_plan.departure_plan_no",
        child=f"{MTP}.cs_bt_train_operation_log.departure_plan_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 40, 40, 11, 14, 14),
        reason="作业日志同时写下开行计划编号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_LOG,
                method="buildPlanLog",
                snippet="log.setDeparturePlanNo(plan.getDeparturePlanNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_train_operation_tracking.id",
        child=f"{MTP}.cs_bt_train_operation_exception_record.operation_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 1, 1, 1, 3, 3),
        reason="异常记录挂作业跟踪主键，一条作业可登记多次异常",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_EXCEPTION,
                method="fillOperationSnapshot",
                snippet="record.setOperationId(operation.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_departure_plan.departure_plan_no",
        child=f"{MTP}.cs_bt_train_operation_exception_record.departure_plan_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 1, 1, 1, 14, 14),
        reason="异常记录从作业快照拷开行计划编号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_EXCEPTION,
                method="fillOperationSnapshot",
                snippet="record.setDeparturePlanNo(operation.getDeparturePlanNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_payment_apply.id",
        child=f"{MTP}.cs_dsly_settlement_payable_bill.payment_apply_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 23, 9, 9, 9, 9),
        reason="批量提交付款申请时把同一申请主键写到多张应付账单",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_SETTLE_PAYABLE_ADMIN,
                method="batchSubmitPayment",
                snippet="item.setPaymentApplyId(paymentApply.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_payment_apply.id",
        child=f"{MTP}.cs_dsly_settlement_payment_relation.payment_apply_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 9, 9, 9, 9, 9),
        reason="生成付款申请时循环挂同一申请主键",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_SETTLE_APPLY,
                method="createPaymentRelation",
                snippet="paymentRelation.setPaymentApplyId(paymentApply.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_payment_apply.id",
        child=f"{MTP}.cs_dsly_settlement_payment_approval_history.payment_apply_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 7, 7, 7, 9, 9),
        reason="审批历史从付款申请主键落库，一申请可多次审批",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SETTLE_APPLY,
                method="createApprovalHistory",
                snippet="paymentApplyHistory.setPaymentApplyId(paymentApply.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_payment_apply.payment_apply_no",
        child=f"{MTP}.cs_dsly_settlement_payment_approval_history.payment_apply_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 7, 7, 7, 9, 9),
        reason="审批历史同时写下付款申请编号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SETTLE_APPLY,
                method="createApprovalHistory",
                snippet="paymentApplyHistory.setPaymentApplyNo(paymentApply.getPaymentApplyNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_payment_apply.id",
        child=f"{MTP}.cs_dsly_settlement_prepayment.payment_apply_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 9, 9),
        reason="预付单批量发起付款申请时写入申请主键；UAT 尚无预付行",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_SETTLE_PREPAY,
                method="batchPaymentApply",
                snippet="item.setPaymentApplyId(paymentApply.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_prepayment.id",
        child=f"{MTP}.cs_dsly_settlement_prepayment_bill.prepayment_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="预付核销行挂预付单主键；两端 UAT 均无行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SETTLE_PREPAY_BILL,
                method="calBillVerifyAmount",
                snippet="prepaymentBill.setPrepaymentId(prepaymentBillQuery.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_payable_bill.id",
        child=f"{MTP}.cs_dsly_settlement_prepayment_bill.bill_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 23, 23),
        reason="预付核销行挂应付账单主键；UAT 尚无核销行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SETTLE_PREPAY_BILL,
                method="calBillVerifyAmount",
                snippet="prepaymentBill.setBillId(payableBill.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_sales_invoice.id",
        child=f"{MTP}.cs_dsly_settlement_expense.sales_invoice_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 121, 8, 5, 7, 7, orphan_keys=1),
        reason="开票时循环把同一发票主键写到多条费用",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_SETTLE_INVOICE,
                method="save",
                snippet="expense.setSalesInvoiceId(salesInvoiceItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_order_entrusted_order.entrusted_order_no",
        child=f"{MTP}.cs_dsly_settlement_expense.entrusted_order_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 121, 121, 41, 89, 89),
        reason="费用从运输结算 MQ 拷委托订单号，一单可生成多条费用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SETTLE_EXPENSE,
                method="buildExpenseCommon",
                snippet="expense.setEntrustedOrderNo(settlementExpenseMqQuery.getEntrustedOrderNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_expense.expense_no",
        child=f"{MTP}.cs_dsly_settlement_expense_modify_log.expense_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 12, 9, 8, 120, 120),
        reason="改价日志按费用编号落库，一笔费用可记多次",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SETTLE_LOG,
                method="insertModifyLog",
                snippet="modifyLog.setExpenseNo(expenseNo);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_daily_plan.id",
        child=f"{MTP}.cs_dsly_settlement_bt_expense.daily_plan_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 36, 36, 17, 27, 27, orphan_keys=2),
        reason="运单到站生成班列费用时挂日计划主键",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_WAYBILL,
                method="createArrivalPayableExpense",
                snippet="expenseItem.setDailyPlanId(waybill.getDailyPlanId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_daily_plan.daily_plan_no",
        child=f"{MTP}.cs_dsly_settlement_bt_expense.daily_plan_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 36, 36, 17, 27, 27, orphan_keys=2),
        reason="班列费用同时写下日计划编号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_WAYBILL,
                method="createArrivalPayableExpense",
                snippet="expenseItem.setDailyPlanNo(waybill.getDailyPlanNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_waybill.id",
        child=f"{MTP}.cs_dsly_settlement_bt_expense.waybill_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 36, 36, 17, 19, 19, orphan_keys=2),
        reason="运单到站生成应收/应付费用，一运单可对应两类费用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_WAYBILL,
                method="createArrivalPayableExpense",
                snippet="expenseItem.setWaybillId(waybill.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_waybill.waybill_no",
        child=f"{MTP}.cs_dsly_settlement_bt_expense.waybill_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 36, 36, 17, 19, 19, orphan_keys=2),
        reason="班列费用同时写下运单编号",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_WAYBILL,
                method="createArrivalPayableExpense",
                snippet="expenseItem.setWaybillNo(waybill.getWaybillNo());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_route.id",
        child=f"{MTP}.cs_dsly_settlement_bt_expense.route_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 36, 33, 5, 5, 5),
        reason="班列费用从运单线路主键落库，一条线路可对应多笔费用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_WAYBILL,
                method="createArrivalPayableExpense",
                snippet="expenseItem.setRouteId(route.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_bt_expense.expense_no",
        child=f"{MTP}.cs_dsly_settlement_bt_expense_modify_log.expense_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 1, 1, 1, 36, 36),
        reason="班列费用改价日志按费用编号落库",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SETTLE_BT_LOG,
                method="insertModifyLog",
                snippet="modifyLog.setExpenseNo(expenseNo);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_owner_fund.id",
        child=f"{MTP}.cs_dsly_settlement_owner_fund_flow.owner_fund_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="充值流水挂货主资金账户主键；两端 UAT 均无行",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SETTLE_FLOW,
                method="confirmReceipt",
                snippet="flowItem.setOwnerFundId(ownerFund.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_receivable_bill.id",
        child=f"{MTP}.cs_dsly_settlement_operation_fee_detail.bill_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 35, 35),
        reason="港口作业费明细生成应收账单后回写账单主键；UAT 无明细行",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_SETTLE_OP_FEE,
                method="generateBillingOrder",
                snippet="item.setBillId(receivableBill.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_payment_confirmation.id",
        child=f"{MTP}.cs_dsly_settlement_payment_verification.payment_confirmation_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 8, 8, 8, 8, 8),
        reason="核销行从入参确认单主键落库，一确认单可挂多张业务单",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SETTLE_PAY_VERIFY,
                method="save",
                snippet="Long paymentConfirmationId = paymentVerificationItem.getPaymentConfirmationId();",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_settlement_receipt_confirmation.id",
        child=f"{MTP}.cs_dsly_settlement_receipt_verification.receipt_confirmation_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 5, 5, 4, 9, 9),
        reason="收款核销从入参确认单主键落库，一确认单可加入多张计费单",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_SETTLE_RCV_VERIFY,
                method="save",
                snippet="ReceiptVerification receiptVerification = findFirst(new ConditionRule().andEqual(ReceiptVerification::getBusinessId, item.getBusinessId()).andEqual(ReceiptVerification::getReceiptConfirmationId, item.getReceiptConfirmationId()));",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_station.id",
        child=f"{MTP}.cs_bt_route_station.station_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 18, 18, 9, 0, 0, orphan_keys=9),
        reason="线路过程站点从保存入参拷场站主键；UAT 场站主表当前为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_ROUTE,
                method="syncRouteStations",
                snippet="BtRouteStation station = Convert.convert(BtRouteStation.class, stationItem);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_bt_station.station_code",
        child=f"{MTP}.cs_bt_route_station.station_code",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 18, 18, 9, 0, 0, orphan_keys=9),
        reason="线路过程站点同时从保存入参拷场站编号；UAT 场站主表当前为空",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_ROUTE,
                method="syncRouteStations",
                snippet="BtRouteStation station = Convert.convert(BtRouteStation.class, stationItem);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo_category.category_code",
        child=f"{MTP}.cs_bt_monthly_entrusted.cargo_category_code",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 25, 25, 4, 6, 6, orphan_keys=1),
        reason="月度需求按货物品类编码保存，一种品类可用于多张需求",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_MONTHLY,
                method="save",
                snippet="MonthlyEntrusted monthlyEntrusted = BeanUtil.toBean(item, MonthlyEntrusted.class);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_cargo.cargo_code",
        child=f"{MTP}.cs_bt_monthly_entrusted.cargo_code",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 25, 25, 8, 48, 48),
        reason="月度需求按货物编码保存，同一种货物可用于多张需求",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_BT_MONTHLY,
                method="save",
                snippet="MonthlyEntrusted monthlyEntrusted = BeanUtil.toBean(item, MonthlyEntrusted.class);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_basic_expense_config.expense_code",
        child=f"{MTP}.cs_dsly_settlement_bt_expense.expense_code",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 36, 36, 4, 7, 7, orphan_keys=2),
        reason="班列费用按启用的费用科目编码生成，同一科目可用于多笔费用",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_BT_WAYBILL,
                method="createArrivalPayableExpense",
                snippet="expenseItem.setExpenseCode(expenseConfig.getExpenseCode());",
            ),
        ),
    ),
    # ---- cs_dsly_declaration_*：UAT 全表空，六个数字均为 0。
    SeedEdge(
        parent=f"{MTP}.cs_dsly_declaration_order.id",
        child=f"{MTP}.cs_dsly_declaration_order_transport.declaration_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="运输信息按报关单主键查已有行再 upsert，一单一条运输",
        sites=(
            SeedSite(
                kind="single_write",
                file=_DECL_TRANSPORT,
                method="save",
                snippet="orderTransportItem.setDeclarationId(orderId);",
            ),
            SeedSite(
                kind="lossy_read",
                file=_DECL_TRANSPORT,
                method="findByOrderId",
                snippet="return dao.findFirst(conditionRule);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_declaration_order.id",
        child=f"{MTP}.cs_dsly_declaration_order_declare.declaration_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="申报信息按报关单主键查已有行再 upsert，一单一条申报",
        sites=(
            SeedSite(
                kind="single_write",
                file=_DECL_DECLARE,
                method="save",
                snippet="orderDeclareItem.setDeclarationId(orderId);",
            ),
            SeedSite(
                kind="lossy_read",
                file=_DECL_DECLARE,
                method="findByOrderId",
                snippet="return dao.findFirst(conditionRule);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_declaration_order.id",
        child=f"{MTP}.cs_dsly_declaration_order_quarantine.declaration_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="检验检疫按报关单主键查已有行再 upsert，一单一条检疫",
        sites=(
            SeedSite(
                kind="single_write",
                file=_DECL_QUARANTINE,
                method="save",
                snippet="orderQuarantineItem.setDeclarationId(orderId);",
            ),
            SeedSite(
                kind="lossy_read",
                file=_DECL_QUARANTINE,
                method="findByOrderId",
                snippet="return dao.findFirst(conditionRule);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_declaration_order.id",
        child=f"{MTP}.cs_dsly_declaration_order_cargo.declaration_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="货物批量保存时循环写入同一报关单主键，一单可多货",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_DECL_CARGO,
                method="batchSave",
                snippet="orderCargoItem.setDeclarationId(orderId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_declaration_order.id",
        child=f"{MTP}.cs_dsly_declaration_order_container.declaration_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="集装箱批量保存时循环写入同一报关单主键，一单可多箱",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_DECL_CONTAINER,
                method="batchSave",
                snippet="orderContainerItem.setDeclarationId(declarationId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_declaration_order.id",
        child=f"{MTP}.cs_dsly_declaration_order_document.declaration_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="随附单据批量保存时循环写入同一报关单主键，一单可多证",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_DECL_DOCUMENT,
                method="batchSave",
                snippet="orderDocumentItem.setDeclarationId(declarationId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_declaration_order_quarantine.id",
        child=f"{MTP}.cs_dsly_declaration_order_quarantine_enterprise.parent_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="检疫企业资质批量挂到同一检疫主键，一条检疫可多家企业",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_DECL_ENTERPRISE,
                method="batchSave",
                snippet="quarantineEnterpriseItem.setParentId(quarantineId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_declaration_order_cargo.id",
        child=f"{MTP}.cs_dsly_declaration_order_cargo_attribute.parent_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="新货物落库后立刻挂一条属性行，按货物主键一对一写入",
        sites=(
            SeedSite(
                kind="single_write",
                file=_DECL_CARGO,
                method="batchSave",
                snippet="orderCargoAttribute.setParentId(orderCargo.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_declaration_commodity_catalog.id",
        child=f"{MTP}.cs_dsly_declaration_commodity.parent_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="商品保存时把章目录主键写入 parentId，一章下可挂多个 HS 商品",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_DECL_COMMODITY,
                method="save",
                snippet="commodityItem.setParentId(chapterCatalog.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_declaration_basic_information.id",
        child=f"{MTP}.cs_dsly_declaration_commodity_basic_data.type_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="商品基础资料导入时把基础信息主键写入 typeId，一类可多条资料",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_DECL_BASIC_DATA,
                method="parseCommodityBasicDataInfoSheet",
                snippet="commodityBasicDataAdminItem.setTypeId(basicInformation.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_declaration_entrust.entrusted_no",
        child=f"{MTP}.cs_dsly_declaration_order.entrust_protocol_no",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 0, 0),
        reason="报关订单从委托选择器回填委托协议号，同一委托协议可用于多张报关单",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_DECL_ORDER_EDIT,
                method="confirmEntrust",
                snippet="formData.value.entrustProtocolNo = selectedEntrust.value.entrustedNo;",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_declaration_commodity_catalog.id",
        child=f"{MTP}.cs_dsly_declaration_commodity_catalog.parent_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="商品目录用 parentId 形成类号到章号的父子树，一个上级目录可包含多个下级目录",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_DECL_CATALOG,
                method="saveOrUpdate",
                snippet="boolean b = dao.saveOrUpdate(item);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{MTP}.cs_dsly_declaration_commodity.commodity_code",
        child=f"{MTP}.cs_dsly_declaration_order_cargo.commodity_code",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("text", 0, 0, 0, 0, 0),
        reason="报关货物从 HS 商品目录回填商品编码，同一商品编码可用于多条报关货物",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_DECL_CARGO_EDIT,
                method="confirmCommodityDeclare",
                snippet="formData.value.commodityCode = commodityDeclareData.value.commodityCode;",
            ),
        ),
    ),
    # ---- cs_portal_member_*（c12_portal_db.uat_portal）
    SeedEdge(
        parent=f"{PORTAL}.cs_portal_member_user_info.id",
        child=f"{PORTAL}.cs_portal_member_user_auth_info.user_info_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 395, 395, 212, 222, 222),
        reason="会员角色认证行绑定本地会员主键，一个会员可挂多个角色认证",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_MEMBER_USER,
                method="buildUserAuthInfo",
                snippet="authInfo.setUserInfoId(userInfoId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{PORTAL}.cs_portal_member_user_info.id",
        child=f"{PORTAL}.cs_portal_member_user_identity_auth_detail.user_info_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 320, 320, 197, 222, 222),
        reason="身份认证快照按角色批量写入同一会员主键，一个会员可有多份快照",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_MEMBER_AUTH_DETAIL,
                method="saveOrUpdateBySnapshot",
                snippet="target.setUserInfoId(userInfoId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{PORTAL}.cs_portal_member_user_identity_auth_detail.id",
        child=f"{PORTAL}.cs_portal_member_user_auth_info.auth_detail_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 395, 365, 311, 320, 320),
        reason="角色认证行回填身份快照主键；UAT 存在同一快照被多行引用",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_MEMBER_USER,
                method="createAndSaveUserAuthInfo",
                snippet="mainRoleAuth.setAuthDetailId(authDetailId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{PORTAL}.cs_portal_member_contract.id",
        child=f"{PORTAL}.cs_portal_member_contract_operation.contract_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 0, 0, 0, 28, 28),
        reason="港口作业合同保存时按合同主键查已有作业行再 upsert，一合同一条作业扩展",
        sites=(
            SeedSite(
                kind="single_write",
                file=_MEMBER_CONTRACT,
                method="save",
                snippet="item.getContractOperationAdminItem().setContractId(item.getId());",
            ),
            SeedSite(
                kind="lossy_read",
                file=_MEMBER_CONTRACT,
                method="save",
                snippet=(
                    "ContractOperation first = contractOperationAdminService.findFirst("
                    "new ConditionRule().andEqual(ContractOperation::getContractId, item.getId()));"
                ),
            ),
        ),
    ),
    SeedEdge(
        parent=f"{PORTAL}.cs_portal_member_contract.id",
        child=f"{PORTAL}.cs_portal_member_contract_quote_info.contract_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 28, 28),
        reason="港口作业合同报价先删后批量插入，同一合同主键可挂多条报价",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_MEMBER_CONTRACT,
                method="save",
                snippet="data.setContractId(item.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{PORTAL}.cs_portal_member_shipper_level.id",
        child=f"{PORTAL}.cs_portal_member_shipper_level_history.level_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 2, 2),
        reason="货主等级评定确认时写入历史，同一等级主表可积累多条历史",
        sites=(
            SeedSite(
                kind="caller_key_reuse",
                file=_MEMBER_LEVEL,
                method="save",
                snippet="shipperLevelHistory.setLevelId(shipperLevelItem.getId());",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{PORTAL}.cs_portal_member_attachment.id",
        child=f"{PORTAL}.cs_portal_member_shipper_level_history.member_attachment_id",
        code_cardinality="one_to_one",
        code_evidence="single_write",
        measured=SeedMeasurement("numeric", 0, 0, 0, 15, 15),
        reason="等级历史可选挂一条评定附件主键，写入时一对一回填",
        sites=(
            SeedSite(
                kind="single_write",
                file=_MEMBER_LEVEL,
                method="save",
                snippet=(
                    "attachmentOpt.ifPresent(attachment -> "
                    "shipperLevelHistory.setMemberAttachmentId(attachment.getId()));"
                ),
            ),
        ),
    ),
    # ---- cs_portal_cockpit_*（UAT 全空；仅两条模块内 FK）
    SeedEdge(
        parent=f"{PORTAL}.cs_portal_cockpit_city_flow.id",
        child=f"{PORTAL}.cs_portal_cockpit_city_flow_cargo.flow_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="城市流向节点落库后循环写入货类明细，同一流向主键可挂多条货类",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_COCKPIT_DATA,
                method="saveCityFlowCargo",
                snippet="entity.setFlowId(flowId);",
            ),
        ),
    ),
    SeedEdge(
        parent=f"{PORTAL}.cs_portal_cockpit_cargo_summary.id",
        child=f"{PORTAL}.cs_portal_cockpit_cargo_category.summary_id",
        code_cardinality="one_to_many",
        code_evidence="batch_allowed",
        measured=SeedMeasurement("numeric", 0, 0, 0, 0, 0),
        reason="货量汇总节点下批量写入货类占比；区域/企业归属时 summaryId 可为空",
        sites=(
            SeedSite(
                kind="shared_key_fanout",
                file=_COCKPIT_DATA,
                method="saveCategories",
                snippet="entity.setSummaryId(summaryId);",
            ),
        ),
    ),
)


SEED_WRITES: tuple[SeedWrite, ...] = (
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_address",
        kind="save_or_update",
        file=_BASIC_ADMIN,
        method="save",
        snippet="saveOrUpdate(addressAdminItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_address",
        kind="batch_insert",
        file=_BASIC_ADMIN,
        method="batchSaveAddress",
        snippet="batchInsert(addressList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_address",
        kind="save_or_update",
        file=_BASIC_PORTAL,
        method="save",
        snippet="saveOrUpdate(addressAdminItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_address",
        kind="batch_insert",
        file=_BASIC_PORTAL,
        method="batchSaveAddress",
        snippet="batchInsert(addressList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_carrier_order",
        kind="batch_insert",
        file=_CARRIER_ADMIN,
        method="batchCreateCarrierOrder",
        snippet=(
            "HighwayCarrierOrder carrierOrder = buildCarrierOrder("
            "carrierOrderAdminQuery, carrierOrderChildItem, carrierOrderNo);\n"
            "insertCarrierOrderList.add(carrierOrder);\n"
            "carrierOrderDao.batchInsert(insertCarrierOrderList);"
        ),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_cargo",
        kind="batch_insert",
        file=_CARRIER_ADMIN,
        method="batchCreateCarrierOrder",
        snippet=(
            "HighwayCargo cargo = buildCarrierCargo("
            "cargoAdminQuery, carrierOrderChildItem, carrierOrderNo);\n"
            "insertCargoList.add(cargo);\n"
            "cargoDao.batchInsert(insertCargoList);"
        ),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_cargo",
        kind="batch_insert",
        file=_CARRIER_PORTAL,
        method="batchDispatchOrder",
        snippet=(
            "HighwayCargo dispatchCargo = buildDispatchCargo("
            "carrierCargo, dispatchOrderNo, dispatchChildItem);\n"
            "insertCargoList.add(dispatchCargo);\n"
            "cargoDao.batchInsert(insertCargoList);"
        ),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_carrier_settlement",
        kind="batch_insert",
        file=_CARRIER_ADMIN,
        method="batchCreateCarrierOrder",
        snippet=(
            "Settlement settlement = buildSettlement("
            "carrierOrderChildItem, carrierOrderNo);\n"
            "insertSettlementList.add(settlement);\n"
            "settlementAdminService.batchInsert(insertSettlementList);"
        ),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_dispatch_order",
        kind="batch_insert",
        file=_CARRIER_PORTAL,
        method="batchDispatchOrder",
        snippet=(
            "HighwayDispatchOrder dispatchOrder = buildDispatchOrder("
            "carrierOrder, dispatchOrderNo, dispatchChildItem);\n"
            "insertDispatchOrderList.add(dispatchOrder);\n"
            "dispatchOrderDao.batchInsert(insertDispatchOrderList);"
        ),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_inbound_order",
        kind="save_or_update",
        file=_INBOUND_CREATE,
        method="createAndPublish",
        snippet=(
            "HighwayInboundOrder inboundOrder = buildInboundOrder("
            "dispatchOrder, carrierOrder, source, loadTime, now);\n"
            "inboundOrderDao.saveOrUpdate(inboundOrder);"
        ),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_inbound_order_cargo",
        kind="save_or_update",
        file=_INBOUND_CREATE,
        method="createAndPublish",
        snippet=(
            "HighwayInboundOrderCargo inboundCargo = buildInboundCargo("
            "inboundOrder, cargo, estimatedNumber);\n"
            "inboundOrderCargoDao.saveOrUpdate(inboundCargo);"
        ),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_cargo",
        kind="save_or_update",
        file=_SHIPPING_ADMIN,
        method="batchCreateCarrierOrder",
        snippet="cargoDao.saveOrUpdate(cargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_dispatch_record",
        kind="batch_insert",
        file=_CARRIER_PORTAL,
        method="batchDispatchOrder",
        snippet=(
            "if(CollUtil.isNotEmpty(insertRecordList)) {\n"
            "    recordPortalService.batchInsert(insertRecordList);\n"
            "}"
        ),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_dispatch_record",
        kind="save_or_update",
        file=_DISPATCH_PORTAL,
        method="load",
        snippet="routePortalService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_dispatch_record",
        kind="save_or_update",
        file=_DISPATCH_PORTAL,
        method="modifyLoadInfo",
        snippet="routePortalService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_dispatch_record",
        kind="save_or_update",
        file=_DISPATCH_PORTAL,
        method="unload",
        snippet="routePortalService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_dispatch_record",
        kind="save_or_update",
        file=_DISPATCH_PORTAL,
        method="modifyUnloadInfo",
        snippet="routePortalService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_dispatch_record",
        kind="save_or_update",
        file=_DISPATCH_PORTAL,
        method="redispatch",
        snippet="routePortalService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_dispatch_record",
        kind="save_or_update",
        file=_DISPATCH_ADMIN,
        method="sign",
        snippet="routePortalService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_park_appointment",
        kind="save_or_update",
        file=_PARK_PORTAL,
        method="report",
        snippet=(
            "HighwayParkAppointment appointment = buildAppointment("
            "item, dispatchOrder, park, responseData.getData());\n"
            "saveOrUpdate(appointment);"
        ),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_park_appointment",
        kind="save_or_update",
        file=_PARK_PORTAL,
        method="reappoint",
        snippet=(
            "HighwayParkAppointment appointment = buildAppointment("
            "item, dispatchOrder, park, responseData.getData());\n"
            "saveOrUpdate(appointment);"
        ),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_dispatch_box_relation",
        kind="batch_insert",
        file=_DISPATCH_BOX,
        method="sync",
        snippet="relationDao.batchInsert(inserts);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_risk_bypass_log",
        kind="save_or_update",
        file=_RISK_GATE,
        method="saveBypassLog",
        snippet="dao.saveOrUpdate(log);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_inbound_receipt_sync_record",
        kind="save_or_update",
        file=_WMS_SYNC,
        method="processReceipt",
        snippet=(
            "HighwayInboundReceiptSyncRecord record =\n"
            "        buildReceiptRecord(message, inboundOrder, cargo, now);\n"
            "receiptSyncRecordDao.saveOrUpdate(record);"
        ),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_container",
        kind="batch_insert",
        file=_CARRIER_ADMIN,
        method="batchCreateCarrierOrder",
        snippet=(
            "if(CollUtil.isNotEmpty(insertContainerList)){\n"
            "    containerDao.batchInsert(insertContainerList);\n"
            "}"
        ),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_container",
        kind="batch_insert",
        file=_CONTAINER_PORTAL,
        method="batchProcessContainerInfo",
        snippet=("if (CollUtil.isNotEmpty(containers)) {\n    dao.batchInsert(containers);\n}"),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_container",
        kind="save_or_update",
        file=_CONTAINER_PORTAL,
        method="reDispatchModifyContainerInfo",
        snippet="saveOrUpdate(container);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_attachment",
        kind="batch_insert",
        file=_ATTACHMENT_BASIC,
        method="batchInsertWithDispatchId",
        snippet=(
            "attachment.setSourceId(dispatchId);\n"
            "                attachment.setSource(HighwaySourceTypeEnum.DISPATCH.getCode());\n"
            "                preSave(attachment);\n"
            "            }\n"
            "            batchInsert(dispatchAttachment);"
        ),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_attachment",
        kind="batch_insert",
        file=_CONTAINER_PORTAL,
        method="saveContainerAttachment",
        snippet="attachmentPortalService.batchInsert(dispatchAttachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_attachment",
        kind="batch_insert",
        file=_DISPATCH_ADMIN,
        method="sign",
        snippet="attachmentAdminService.batchInsert(allSignAttachments);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_attachment",
        kind="save_or_update",
        file=_ATTACHMENT_ADMIN,
        method="uploadAndSave",
        snippet="saveOrUpdate(attachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_attachment",
        kind="save_or_update",
        file=_ENTRUSTED_ORDER_ADMIN,
        method="upload",
        snippet="highwayCarrierAttachmentAdminLocalApi.saveOrUpdate(carrierAttachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_highway_attachment",
        kind="save_or_update",
        file=_ATTACHMENT_ADMIN_CONTROLLER,
        method="saveOrUpdate",
        snippet="attachmentAdminService.saveOrUpdate(carrierAttachmentAdminItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_carrier_order",
        kind="batch_insert",
        file=_RW_CARRIER_ADMIN,
        method="batchCreateCarrierOrder",
        snippet="batchInsert(insertCarrierOrderList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_cargo",
        kind="batch_insert",
        file=_RW_CARRIER_ADMIN,
        method="batchCreateCarrierOrder",
        snippet="cargoDao.batchInsert(insertCargoList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_cargo",
        kind="save_or_update",
        file=_RW_DISPATCH_BASIC,
        method="batchDispatchOrderGt",
        snippet="cargoDao.saveOrUpdate(cargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_cargo",
        kind="save_or_update",
        file=_RW_CARRIER_BASIC,
        method="batchDispatchOrder",
        snippet="cargoDao.saveOrUpdate(cargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_carrier_settlement",
        kind="batch_insert",
        file=_RW_CARRIER_ADMIN,
        method="batchCreateCarrierOrder",
        snippet="railwayCarrierSettlementAdminService.batchInsert(insertSettlementList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_order",
        kind="save_or_update",
        file=_RW_DISPATCH_BASIC,
        method="batchDispatchOrderGt",
        snippet="dao.saveOrUpdate(dispatchOrder);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_order",
        kind="save_or_update",
        file=_RW_CARRIER_BASIC,
        method="batchDispatchOrder",
        snippet="dao.saveOrUpdate(dispatchOrder);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_record",
        kind="batch_insert",
        file=_RW_DISPATCH_BASIC,
        method="batchDispatchOrderGt",
        snippet="recordBasicService.batchInsert(records);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_record",
        kind="save_or_update",
        file=_RW_CARRIER_BASIC,
        method="batchDispatchOrder",
        snippet="recordBasicService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_record",
        kind="save_or_update",
        file=_RW_DISPATCH_BASIC,
        method="load",
        snippet="recordBasicService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_record",
        kind="save_or_update",
        file=_RW_DISPATCH_BASIC,
        method="modifyLoadInfo",
        snippet="recordBasicService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_record",
        kind="save_or_update",
        file=_RW_DISPATCH_BASIC,
        method="unload",
        snippet="recordBasicService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_record",
        kind="save_or_update",
        file=_RW_DISPATCH_BASIC,
        method="modifyUnloadInfo",
        snippet="recordBasicService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_record",
        kind="save_or_update",
        file=_RW_DISPATCH_BASIC,
        method="sign",
        snippet="recordBasicService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_record",
        kind="save_or_update",
        file=_RW_DISPATCH_BASIC,
        method="depart",
        snippet="recordBasicService.saveOrUpdate(route);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_record",
        kind="save_or_update",
        file=_RW_DISPATCH_BASIC,
        method="arrive",
        snippet="recordBasicService.saveOrUpdate(route);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_record",
        kind="save_or_update",
        file=_RW_DISPATCH_BASIC,
        method="redispatch",
        snippet="recordBasicService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_record",
        kind="batch_insert",
        file=_RW_DISPATCH_ADMIN,
        method="processDisptachRecords",
        snippet="recordAdminService.batchInsert(recordListAdd);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_order_line",
        kind="batch_insert",
        file=_RW_DISPATCH_BASIC,
        method="batchSaveOrUpdateLine",
        snippet="dispatchOrderLineBasicService.batchInsert(addStationList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_order_line",
        kind="batch_insert",
        file=_RW_DISPATCH_ADMIN,
        method="processDispatchOrderLines",
        snippet="dispatchOrderLineAdminService.batchInsert(lineListAdd);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_manifest",
        kind="batch_insert",
        file=_RW_DISPATCH_BASIC,
        method="batchDispatchOrderGt",
        snippet="dispatchManifestDao.batchInsert(dispatchManifests);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_manifest",
        kind="batch_insert",
        file=_RW_DISPATCH_ADMIN,
        method="updateOrCreateManifest",
        snippet="dispatchManifestAdminService.batchInsert(manifestListAdd);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_dispatch_manifest",
        kind="save_or_update",
        file=_RW_MANIFEST_BASIC,
        method="saveDispatchManifest",
        snippet="dao.saveOrUpdate(dispatchManifest);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_daily_plan",
        kind="batch_insert",
        file=_RW_DAILY_BASIC,
        method="bindDailyPlan",
        snippet="this.batchInsert(dailyPlans);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_daily_plan",
        kind="save_or_update",
        file=_RW_DISPATCH_ADMIN,
        method="processTraceResult",
        snippet="railwayDailyPlanDao.saveOrUpdate(dailyPlan);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_carrier_order_container",
        kind="batch_insert",
        file=_RW_CARRIER_ADMIN,
        method="batchCreateCarrierOrder",
        snippet="carrierContainerAdminService.batchInsert(containerList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_attachment",
        kind="batch_insert",
        file=_RW_DISPATCH_BASIC,
        method="load",
        snippet="attachmentBasicService.batchInsert(dispatchAttachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_attachment",
        kind="batch_insert",
        file=_RW_DISPATCH_BASIC,
        method="modifyLoadInfo",
        snippet="attachmentBasicService.batchInsert(dispatchAttachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_attachment",
        kind="batch_insert",
        file=_RW_DISPATCH_BASIC,
        method="unload",
        snippet="attachmentBasicService.batchInsert(dispatchAttachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_attachment",
        kind="batch_insert",
        file=_RW_DISPATCH_BASIC,
        method="modifyUnloadInfo",
        snippet="attachmentBasicService.batchInsert(dispatchAttachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_attachment",
        kind="batch_insert",
        file=_RW_DISPATCH_BASIC,
        method="sign",
        snippet="attachmentBasicService.batchInsert(allSignAttachments);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_attachment",
        kind="batch_insert",
        file=_RW_CARRIER_BASIC,
        method="batchSaveAttachment",
        snippet="attachmentBasicService.batchInsert(attachments);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_railway_attachment",
        kind="save_or_update",
        file=_RW_ATTACHMENT_BASIC,
        method="uploadAndSave",
        snippet="saveOrUpdate(attachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_carrier_order",
        kind="save_or_update",
        file=_SHIPPING_ADMIN,
        method="batchCreateCarrierOrder",
        snippet="saveOrUpdate(carrierOrder);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_cargo",
        kind="save_or_update",
        file=_SHIPPING_PORTAL,
        method="handleCreateDispatch",
        snippet="cargoDao.saveOrUpdate(dispatchCargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_carrier_settlement",
        kind="save_or_update",
        file=_SHIPPING_ADMIN,
        method="batchCreateCarrierOrder",
        snippet="shippingCarrierSettlementAdminService.saveOrUpdate(settlement);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_dispatch_order",
        kind="save_or_update",
        file=_SHIPPING_PORTAL,
        method="handleCreateDispatch",
        snippet="dao.saveOrUpdate(dispatchOrder);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_dispatch_record",
        kind="save_or_update",
        file=_SHIPPING_PORTAL,
        method="handleCreateDispatch",
        snippet="routePortalService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_dispatch_record",
        kind="save_or_update",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="load",
        snippet="recordPortalService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_dispatch_record",
        kind="save_or_update",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="modifyLoadInfo",
        snippet="recordPortalService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_dispatch_record",
        kind="save_or_update",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="unload",
        snippet="recordPortalService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_dispatch_record",
        kind="save_or_update",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="modifyUnloadInfo",
        snippet="recordPortalService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_dispatch_record",
        kind="save_or_update",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="redispatch",
        snippet="recordPortalService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_dispatch_record",
        kind="save_or_update",
        file=_SHIPPING_DISPATCH_ADMIN,
        method="sign",
        snippet="routePortalService.saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_dispatch_manifest",
        kind="save_or_update",
        file=_SHIPPING_MANIFEST_ADMIN_CONTROLLER,
        method="save",
        snippet="dispatchManifestAdminService.saveOrUpdate(dispatchManifest);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_container",
        kind="batch_insert",
        file=_SHIPPING_ADMIN,
        method="batchCreateCarrierOrder",
        snippet="containerAdminService.batchInsert(containerList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_attachment",
        kind="batch_insert",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="load",
        snippet="attachmentPortalService.batchInsert(dispatchAttachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_attachment",
        kind="batch_insert",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="modifyLoadInfo",
        snippet="attachmentPortalService.batchInsert(dispatchAttachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_attachment",
        kind="batch_insert",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="unload",
        snippet="attachmentPortalService.batchInsert(dispatchAttachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_attachment",
        kind="batch_insert",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="modifyUnloadInfo",
        snippet="attachmentPortalService.batchInsert(dispatchAttachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_attachment",
        kind="batch_insert",
        file=_SHIPPING_DISPATCH_ADMIN,
        method="sign",
        snippet="attachmentAdminService.batchInsert(allSignAttachments);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_attachment",
        kind="batch_insert",
        file=_SHIPPING_PORTAL,
        method="batchSaveAttachment",
        snippet="attachmentPortalService.batchInsert(attachmentList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_attachment",
        kind="save_or_update",
        file=_SHIPPING_ATTACHMENT_ADMIN,
        method="uploadAndSave",
        snippet="saveOrUpdate(attachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_shipping_attachment",
        kind="save_or_update",
        file=_SHIPPING_ATTACHMENT_ADMIN_CONTROLLER,
        method="saveOrUpdate",
        snippet=("attachmentAdminService.saveOrUpdate(shippingCarrierMemberAttachmentAdminItem);"),
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_cargo",
        kind="save_or_update",
        file=_CARGO_ADMIN,
        method="saveFromMasterGoods",
        snippet="saveOrUpdate(cargoItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_cargo",
        kind="save_or_update",
        file=_CARGO_ADMIN,
        method="saveCargo",
        snippet="saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_cargo",
        kind="save_or_update",
        file=_CARGO_PORTAL,
        method="saveCargo",
        snippet="saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_cargo",
        kind="save_or_update",
        file=_CARGO_BASIC_SVC,
        method="syncGoodsAuditStatus",
        snippet="return saveOrUpdate(cargo) ? 1 : 0;",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_cargo_category",
        kind="save_or_update",
        file=_CARGO_CATEGORY_ADMIN,
        method="saveCargoCategory",
        snippet="saveOrUpdate(cargoCategory);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_cargo_category",
        kind="save_or_update",
        file=_CARGO_CATEGORY_PORTAL_CTRL,
        method="save",
        snippet="cargoCategoryPortalService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_cargo_base_price_config",
        kind="batch_insert",
        file=_PRICE_ADMIN,
        method="saveImportData",
        snippet="this.batchInsert(cargoBasePriceConfigList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_cargo_base_price_config",
        kind="save_or_update",
        file=_PRICE_BASIC,
        method="save",
        snippet="saveOrUpdate(basePriceConfig);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_business_info",
        kind="save_or_update",
        file=_BUSINESS_ADMIN,
        method="save",
        snippet="saveOrUpdate(business);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_business_info",
        kind="save_or_update",
        file=_BUSINESS_PORTAL,
        method="save",
        snippet="saveOrUpdate(businessItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_business_info",
        kind="save_or_update",
        file=_TEMPLATE_ADMIN,
        method="copyAdd",
        snippet="businessAdminService.saveOrUpdate(formerBusiness);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_expense_config",
        kind="save_or_update",
        file=_EXPENSE_ADMIN,
        method="save",
        snippet="saveOrUpdate(expenseConfig);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_expense_config",
        kind="save_or_update",
        file=_EXPENSE_PORTAL,
        method="save",
        snippet="saveOrUpdate(expenseConfigItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_billing_template",
        kind="save_or_update",
        file=_TEMPLATE_ADMIN,
        method="save",
        snippet="saveOrUpdate(templateItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_billing_template",
        kind="save_or_update",
        file=_TEMPLATE_ADMIN,
        method="copyAdd",
        snippet="saveOrUpdate(copyTemplate);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_billing_template",
        kind="save_or_update",
        file=_TEMPLATE_PORTAL,
        method="save",
        snippet="saveOrUpdate(templateItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_site_fee_item",
        kind="save_or_update",
        file=_SITE_FEE_ADMIN,
        method="save",
        snippet="this.saveOrUpdate(siteFeeCargoAdminItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_site_fee_item",
        kind="save_or_update",
        file=_SITE_FEE_ADMIN,
        method="saveImportData",
        snippet="this.saveOrUpdate(siteFeeCargoAdminItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_site_fee_item",
        kind="save_or_update",
        file=_SITE_FEE_ITEM_CTRL,
        method="save",
        snippet="siteFeeItemService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_site_fee_item_range",
        kind="batch_insert",
        file=_SITE_FEE_RANGE_BASIC,
        method="batchSave",
        snippet="this.batchInsert(siteFeeItemRangeList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_site_fee_item_range",
        kind="save_or_update",
        file=_SITE_FEE_RANGE_CTRL,
        method="save",
        snippet="siteFeeItemRangeService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_site_fee_item_business",
        kind="batch_insert",
        file=_SITE_FEE_ADMIN,
        method="save",
        snippet="siteFeeBusinessAdminService.batchInsert(siteFeeBusinessItemList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_vehicle",
        kind="save_or_update",
        file=_VEHICLE_BASIC,
        method="save",
        snippet="saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_driver",
        kind="save_or_update",
        file=_DRIVER_BASIC,
        method="saveExistsDriver",
        snippet="saveOrUpdate(driver);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_driver",
        kind="save_or_update",
        file=_DRIVER_ADMIN,
        method="carrierSave",
        snippet="saveOrUpdate(driver);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_driver",
        kind="save_or_update",
        file=_DRIVER_PORTAL,
        method="carrierSave",
        snippet="saveOrUpdate(driver);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_driver_info",
        kind="save_or_update",
        file=_DRIVER_INFO,
        method="saveIfAbsent",
        snippet="saveOrUpdate(driverInfo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_ship",
        kind="save_or_update",
        file=_SHIP_ADMIN_CTRL,
        method="save",
        snippet="shipAdminService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_ship",
        kind="save_or_update",
        file=_SHIP_PORTAL_CTRL,
        method="save",
        snippet="shipPortalService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_ship_owner",
        kind="save_or_update",
        file=_SHIP_OWNER_ADMIN_CTRL,
        method="page",
        snippet="shipOwnerAdminService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_ship_owner",
        kind="save_or_update",
        file=_SHIP_OWNER_PORTAL_CTRL,
        method="save",
        snippet="shipOwnerPortalService.saveOrUpdate(shipOwner);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_port",
        kind="save_or_update",
        file=_PORT_ADMIN_SVC,
        method="savePort",
        snippet="saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_basic_outbound_box",
        kind="insert",
        file=_OUTBOUND_BOX_SYNC,
        method="process",
        snippet="outboundBoxDao.insert(outboundBox);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="saveRouteDetails",
        snippet="dao.saveOrUpdate(route);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="batchInsertListAdmin",
        snippet="this.batchInsert(routeList); // ID 会回填到 routeList 中的对象",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="validateImportData",
        snippet="this.saveOrUpdate(routeAdminItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="saveRouteRailway",
        snippet="dao.saveOrUpdate(route);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="createReverseRoute",
        snippet="dao.saveOrUpdate(reverseRoute);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="batchSaveRouteRailway",
        snippet="dao.batchInsert(snapshotRoutes);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route",
        kind="save_or_update",
        file=_LINE_ROUTE_PORTAL,
        method="saveRouteDetails",
        snippet="dao.saveOrUpdate(route);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route",
        kind="batch_insert",
        file=_LINE_ROUTE_BASIC,
        method="copyAndSaveSnapshot",
        snippet="this.batchInsert(insertList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route",
        kind="batch_insert",
        file=_LINE_ROUTE_BASIC,
        method="batchInsertList",
        snippet="this.batchInsert(routeList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_product",
        kind="save_or_update",
        file=_LINE_ROUTE_PRODUCT_ADMIN,
        method="saveOrUpdateInfo",
        snippet="this.saveOrUpdate(routeProduct);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_product",
        kind="save_or_update",
        file=_LINE_ROUTE_PRODUCT_BASIC,
        method="saveOrUpdateInfo",
        snippet="this.saveOrUpdate(routeProduct);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_product",
        kind="save_or_update",
        file=_LINE_ROUTE_PRODUCT_BASIC,
        method="copyRouteProduct",
        snippet="this.saveOrUpdate(routeProduct);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_product",
        kind="save_or_update",
        file=_LINE_ROUTE_PRODUCT_PORTAL,
        method="copyRouteProduct",
        snippet="this.saveOrUpdate(routeProductPortalItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_product_relate",
        kind="batch_insert",
        file=_LINE_PRODUCT_RELATE_ADMIN,
        method="relateRouteProduct",
        snippet="this.batchInsert(routeProductRelateList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_product_relate",
        kind="batch_insert",
        file=_LINE_PRODUCT_RELATE_ADMIN,
        method="bingRelation",
        snippet="this.batchInsert(routeProductRelateList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_product_relate",
        kind="insert",
        file=_LINE_PRODUCT_RELATE_ADMIN,
        method="addRelation",
        snippet="dao.insert(routeProductRelate);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_product_relate",
        kind="batch_insert",
        file=_LINE_PRODUCT_RELATE_BASIC,
        method="relateRouteProduct",
        snippet="this.batchInsert(routeProductRelateList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_product_relate",
        kind="batch_insert",
        file=_LINE_PRODUCT_RELATE_BASIC,
        method="bingRelation",
        snippet="this.batchInsert(routeProductRelateList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_product_relate",
        kind="insert",
        file=_LINE_PRODUCT_RELATE_BASIC,
        method="addRelation",
        snippet="dao.insert(routeProductRelate);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_product_relate",
        kind="batch_insert",
        file=_LINE_PRODUCT_RELATE_PORTAL,
        method="bingRelation",
        snippet="this.batchInsert(routeProductRelateList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_relate",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="batchSaveRouteRailway",
        snippet="routeRelateAdminService.batchInsert(list);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_relate",
        kind="batch_insert",
        file=_LINE_ROUTE_PRODUCT_ADMIN,
        method="saveWholeRoute",
        snippet="routeRelateAdminService.batchInsert(list1);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_relate",
        kind="batch_insert",
        file=_LINE_ROUTE_BASIC,
        method="copyAndSaveSnapshot",
        snippet="routeRelateBasicService.batchInsert(routeRelateItemList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_carrier",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="saveRouteDetails",
        snippet="routeCarrierAdminService.saveOrUpdate(routeCarrier);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_carrier",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="batchInsertListAdmin",
        snippet="routeCarrierAdminService.batchInsert(routeCarrierList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_carrier",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="saveRouteRailway",
        snippet="routeCarrierAdminService.batchInsert(routeCarriers);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_carrier",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="createReverseRoute",
        snippet="routeCarrierAdminService.batchInsert(reverseCarriers);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_carrier",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="batchSaveRouteRailway",
        snippet="routeCarrierAdminService.batchInsert(uniqueCarriers);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_carrier",
        kind="batch_insert",
        file=_LINE_ROUTE_BASIC,
        method="copyAndSaveSnapshot",
        snippet="routeCarrierBasicService.batchInsert(routeCarrierInsertList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_railway",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="saveRouteRailway",
        snippet="routeRailwayAdminService.saveOrUpdate(routeRailway);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_railway",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="createReverseRoute",
        snippet="routeRailwayAdminService.saveOrUpdate(reverseRouteRailway);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_railway",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="batchSaveRouteRailway",
        snippet="routeRailwayAdminService.batchInsert(routeRailwaysToSave);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_railway",
        kind="batch_insert",
        file=_LINE_ROUTE_BASIC,
        method="copyAndSaveSnapshot",
        snippet="routeRailwayBasicService.batchInsert(routeRailwayItemList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_railway_station",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="saveRouteRailway",
        snippet="routeRailwayStationAdminService.batchInsert(routeRailwayStations);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_railway_station",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="createReverseRoute",
        snippet="routeRailwayStationAdminService.batchInsert(reverseRouteRailwayStations);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_railway_station",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="batchSaveRouteRailway",
        snippet="routeRailwayStationAdminService.batchInsert(stationsToSave);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_railway_station",
        kind="save_or_update",
        file=_LINE_RAILWAY_STATION_ADMIN,
        method="saveData",
        snippet="saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_railway_station",
        kind="batch_insert",
        file=_LINE_ROUTE_BASIC,
        method="copyAndSaveSnapshot",
        snippet="routeRailwayStationBasicService.batchInsert(routeRailwayStationInsertList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="save",
        snippet="routeCargoChargeAdminService.saveOrUpdate(routeCargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="batchInsertListAdmin",
        snippet="routeCargoChargeAdminService.batchInsert(chargesToSave);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="validateImportData",
        snippet="routeCargoChargeAdminService.saveOrUpdate(routeCargoCharge);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="saveRouteRailway",
        snippet="routeCargoChargeAdminService.saveOrUpdate(routeCargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="batchSaveRouteRailway",
        snippet="routeCargoChargeAdminService.batchInsert(finalCargoChargesToSave);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge",
        kind="save_or_update",
        file=_LINE_CARGO_CHARGE_ADMIN_CTRL,
        method="save",
        snippet="routeCargoChargeAdminService.saveOrUpdate(routeCargoCharge);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge",
        kind="save_or_update",
        file=_LINE_ROUTE_BASIC,
        method="saveRouteCargoChargo",
        snippet="routeCargoChargeBasicService.saveOrUpdate(routeCargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge",
        kind="save_or_update",
        file=_LINE_ROUTE_BASIC,
        method="copyAndSaveSnapshot",
        snippet="routeCargoChargeBasicService.saveOrUpdate(routeCargoCharge);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge_range",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="save",
        snippet="routeCargoChargeRangeAdminService.batchInsert(routeCargoChargeRangeList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge_range",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="batchInsertListAdmin",
        snippet="routeCargoChargeRangeAdminService.batchInsert(rangesToSave);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge_range",
        kind="batch_insert",
        file=_LINE_CARGO_CHARGE_RANGE_ADMIN,
        method="saveOrUpdateBatch",
        snippet="dao.batchInsert(routeCargoChargeRanges);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge_range",
        kind="save_or_update",
        file=_LINE_CARGO_CHARGE_RANGE_ADMIN_CTRL,
        method="save",
        snippet="routeCargoChargeRangeAdminService.saveOrUpdate(routeCargoChargeRange);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge_range",
        kind="batch_insert",
        file=_LINE_ROUTE_BASIC,
        method="saveRouteCargoChargo",
        snippet="routeCargoChargeRangeBasicService.batchInsert(routeCargoChargeRangeList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge_range",
        kind="batch_insert",
        file=_LINE_ROUTE_BASIC,
        method="copyAndSaveSnapshot",
        snippet="routeCargoChargeRangeBasicService.batchInsert(list);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_inquiry_quote",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="saveAndModify",
        snippet="routeInquiryQuoteDao.saveOrUpdate(routeInquiryQuote);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_inquiry_quote",
        kind="save_or_update",
        file=_LINE_ROUTE_PORTAL,
        method="saveAndModify",
        snippet="routeInquiryQuoteDao.saveOrUpdate(routeInquiryQuote);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_snapshot_quote",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="updateQuote",
        snippet="routeSnapshotQuoteAdminService.saveOrUpdate(routeSnapshotQuote);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_snapshot_quote",
        kind="save_or_update",
        file=_LINE_ROUTE_BASIC,
        method="copyAndSaveSnapshot",
        snippet="routeSnapshotQuoteBasicService.saveOrUpdate(routeSnapshotQuote);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_inquiry",
        kind="save_or_update",
        file=_LINE_ROUTE_INQUIRY_ADMIN,
        method="save",
        snippet="dao.saveOrUpdate(targetRouteInquiry);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_inquiry_quote_plan",
        kind="save_or_update",
        file=_LINE_QUOTE_PLAN_ADMIN,
        method="saveInquiryQuoteRoute",
        snippet="dao.saveOrUpdate(routeInquiryQuotePlan);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_route_inquiry_quote_plan",
        kind="save_or_update",
        file=_LINE_QUOTE_PLAN_PORTAL,
        method="saveInquiryQuoteRoute",
        snippet="dao.saveOrUpdate(routeInquiryQuotePlan);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_station",
        kind="save_or_update",
        file=_LINE_STATION_ADMIN,
        method="saveData",
        snippet="this.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_station",
        kind="batch_insert",
        file=_LINE_STATION_ADMIN,
        method="saveOrUpdateImportItem",
        snippet="insertNum = dao.batchInsert(toInsertItems);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_station",
        kind="save_or_update",
        file=_LINE_STATION_BASIC,
        method="saveData",
        snippet="this.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_approval_user",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="recordAuditRecord",
        snippet="approvalUserAdminService.saveOrUpdate(approvalUserAdminItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_approval_user",
        kind="save_or_update",
        file=_LINE_ROUTE_PRODUCT_ADMIN,
        method="recordAuditRecord",
        snippet="approvalUserAdminService.saveOrUpdate(approvalUserAdminItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_approval_user",
        kind="save_or_update",
        file=_LINE_APPROVAL_USER_ADMIN,
        method="saveOrUpdateApplyUserInfo",
        snippet="dao.saveOrUpdate(approvalUser);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_approval_user",
        kind="save_or_update",
        file=_LINE_APPROVAL_USER_CTRL,
        method="save",
        snippet="approvalUserAdminService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_approval_history",
        kind="batch_insert",
        file=_LINE_ROUTE_ADMIN,
        method="recordAuditRecord",
        snippet="approvalHistoryAdminService.batchInsert(historyList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_approval_history",
        kind="batch_insert",
        file=_LINE_ROUTE_PRODUCT_ADMIN,
        method="recordAuditRecord",
        snippet="approvalHistoryAdminService.batchInsert(historyList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_approval_history",
        kind="insert",
        file=_LINE_APPROVAL_HISTORY_ADMIN,
        method="insert",
        snippet="dao.insert(approvalHistory);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_line_approval_history",
        kind="save_or_update",
        file=_LINE_APPROVAL_HISTORY_CTRL,
        method="save",
        snippet="approvalHistoryAdminService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted",
        kind="save_or_update",
        file=_OP_ENTRUSTED_PORTAL,
        method="savePortal",
        snippet="dao.saveOrUpdate(entrusted);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted",
        kind="save_or_update",
        file=_OP_ENTRUSTED_ADMIN,
        method="saveOrUpdateEntrusted",
        snippet="dao.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_business_type",
        kind="batch_insert",
        file=_OP_ENTRUSTED_PORTAL,
        method="savePortal",
        snippet="entrustedBusinessTypePortalService.batchInsert(list);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_business_type",
        kind="batch_insert",
        file=_OP_ENTRUSTED_ADMIN,
        method="saveOrUpdateEntrusted",
        snippet="entrustedBusinessTypeAdminService.batchInsert(businessTypesList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_business_type",
        kind="batch_insert",
        file=_OP_ENTRUSTED_PORTAL,
        method="updateEntrustedPortal",
        snippet="entrustedBusinessTypePortalService.batchInsert(businessTypesList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_business_cargo",
        kind="batch_insert",
        file=_OP_ENTRUSTED_PORTAL,
        method="savePortal",
        snippet="entrustedBusinessCargoPortalService.batchInsert(entrustedBusinessCargoList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_business_cargo",
        kind="batch_insert",
        file=_OP_ENTRUSTED_ADMIN,
        method="saveOrUpdateEntrusted",
        snippet="entrustedBusinessCargoAdminService.batchInsert(list);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_business_cargo",
        kind="batch_insert",
        file=_OP_ENTRUSTED_PORTAL,
        method="updateEntrustedPortal",
        snippet="entrustedBusinessCargoPortalService.batchInsert(list);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_business_container",
        kind="batch_insert",
        file=_OP_ENTRUSTED_PORTAL,
        method="savePortal",
        snippet="entrustedBusinessContainerPortalService.batchInsert(entrustedBusinessContainerList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_business_container",
        kind="batch_insert",
        file=_OP_ENTRUSTED_ADMIN,
        method="saveOrUpdateEntrusted",
        snippet="entrustedBusinessContainerAdminService.batchInsert(list);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_business_container",
        kind="batch_insert",
        file=_OP_ENTRUSTED_PORTAL,
        method="updateEntrustedPortal",
        snippet="entrustedBusinessContainerPortalService.batchInsert(list);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_quote",
        kind="save_or_update",
        file=_OP_QUOTE_ADMIN,
        method="save",
        snippet="return dao.saveOrUpdate(entrustedQuoteAdminItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_quote",
        kind="save_or_update",
        file=_OP_ENTRUSTED_ADMIN,
        method="againQuote",
        snippet="entrustedQuoteAdminService.saveOrUpdate(quoteAdminItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_quote_info",
        kind="batch_insert",
        file=_OP_ENTRUSTED_ADMIN,
        method="quoteAdmin",
        snippet="entrustedQuoteInfoAdminService.batchInsert(list);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_quote_info",
        kind="batch_insert",
        file=_OP_ENTRUSTED_ADMIN,
        method="againQuote",
        snippet="entrustedQuoteInfoAdminService.batchInsert(list);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_order",
        kind="save_or_update",
        file=_OP_ORDER_BASIC,
        method="save",
        snippet="dao.saveOrUpdate(entrustedOrder);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_entrusted_order",
        kind="batch_insert",
        file=_OP_ORDER_ADMIN,
        method="batchSaveAdmin",
        snippet="dao.batchInsert(orderList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_appointment",
        kind="save_or_update",
        file=_OP_APPOINTMENT_BASIC,
        method="save",
        snippet="dao.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_appointment_vehicle",
        kind="save_or_update",
        file=_OP_VEHICLE,
        method="save",
        snippet="dao.saveOrUpdate(appointmentVehicle);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_pick_up_appointment",
        kind="save_or_update",
        file=_OP_PICKUP,
        method="save",
        snippet="dao.saveOrUpdate(pickUpAppointment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_container",
        kind="save_or_update",
        file=_OP_CONTAINER_BASIC,
        method="save",
        snippet="dao.saveOrUpdate(container);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_general_cargo",
        kind="save_or_update",
        file=_OP_GENERAL_CARGO_BASIC,
        method="save",
        snippet="dao.saveOrUpdate(generalCargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_work_node",
        kind="save_or_update",
        file=_OP_WORKNODE_BASIC,
        method="save",
        snippet="dao.saveOrUpdate(workNode);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_attachment",
        kind="save_or_update",
        file=_OP_ENTRUSTED_PORTAL,
        method="savePortal",
        snippet="attachmentPortalService.saveOrUpdate(attachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_attachment",
        kind="batch_insert",
        file=_OP_ENTRUSTED_ADMIN,
        method="saveOrUpdateEntrusted",
        snippet="attachmentAdminService.batchInsert(list);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_attachment",
        kind="batch_insert",
        file=_OP_ENTRUSTED_PORTAL,
        method="updateEntrustedPortal",
        snippet="attachmentPortalService.batchInsert(list);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_attachment",
        kind="save_or_update",
        file=_OP_ORDER_BASIC,
        method="save",
        snippet="attachmentBasicService.saveOrUpdate(attachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_operation_attachment",
        kind="save_or_update",
        file=_OP_APPOINTMENT_BASIC,
        method="save",
        snippet="attachmentBasicService.saveOrUpdate(attachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted",
        kind="save_or_update",
        file=_ORDER_ENTRUSTED_ADMIN,
        method="saveOrUpdateEntrusted",
        snippet="dao.saveOrUpdate(converted);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted",
        kind="save_or_update",
        file=_ORDER_ENTRUSTED_PORTAL,
        method="saveOrUpdateEntrusted",
        snippet="dao.saveOrUpdate(entrusted);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted",
        kind="save_or_update",
        file=_ORDER_WMS,
        method="process",
        snippet="entrustedDao.saveOrUpdate(entrusted);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted_order",
        kind="save_or_update",
        file=_ENTRUSTED_ORDER_ADMIN,
        method="save",
        snippet="dao.saveOrUpdate(entrustedOrder);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted_order",
        kind="save_or_update",
        file=_ORDER_WORK_PLAN_ADMIN,
        method="save",
        snippet="entrustedOrderDao.saveOrUpdate(entrustedOrder);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted_order_relate",
        kind="batch_insert",
        file=_ORDER_RELATE_ADMIN,
        method="batchSeve",
        snippet="dao.batchInsert(entrustedOrderRelateList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_work_plan",
        kind="save_or_update",
        file=_ORDER_ENTRUSTED_ADMIN,
        method="generatePlanFromContract",
        snippet="workPlanAdminService.saveOrUpdate(workPlan);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_work_plan",
        kind="save_or_update",
        file=_ORDER_WORK_PLAN_PORTAL,
        method="workDistribute",
        snippet="dao.saveOrUpdate(subPlan);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted_quote",
        kind="save_or_update",
        file=_ORDER_QUOTE_ADMIN,
        method="saveQuote",
        snippet="dao.saveOrUpdate(quote);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted_quote",
        kind="save_or_update",
        file=_ORDER_QUOTE_ADMIN,
        method="editQuote",
        snippet="dao.saveOrUpdate(quote);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted_cargo",
        kind="save_or_update",
        file=_ORDER_ENTRUSTED_ADMIN,
        method="saveOrUpdateEntrusted",
        snippet="entrustedCargoService.saveOrUpdate(cargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted_cargo",
        kind="save_or_update",
        file=_ORDER_ENTRUSTED_PORTAL,
        method="saveOrUpdateEntrusted",
        snippet="entrustedCargoService.saveOrUpdate(entrustedCargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted_cargo",
        kind="save_or_update",
        file=_ENTRUSTED_ORDER_ADMIN,
        method="save",
        snippet="entrustedCargoAdminService.saveOrUpdate(entrustedCargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted_cargo",
        kind="save_or_update",
        file=_ORDER_WORK_PLAN_ADMIN,
        method="save",
        snippet="entrustedCargoAdminService.saveOrUpdate(entrustedCargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted_cargo",
        kind="save_or_update",
        file=_ORDER_WMS,
        method="process",
        snippet="entrustedCargoAdminService.saveOrUpdate(entrustedCargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted_order_settlement",
        kind="save_or_update",
        file=_ENTRUSTED_ORDER_ADMIN,
        method="save",
        snippet="entrustedOrderSettlementAdminService.saveOrUpdate(orderSettlement);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted_order_settlement",
        kind="save_or_update",
        file=_ORDER_WORK_PLAN_ADMIN,
        method="save",
        snippet="entrustedOrderSettlementAdminService.saveOrUpdate(settlement);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_entrusted_order_settlement",
        kind="save_or_update",
        file=_ORDER_ENTRUSTED_ADMIN,
        method="generatePlanFromContract",
        snippet="entrustedOrderSettlementAdminService.saveOrUpdate(entrustedOrderSettlement);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_container",
        kind="batch_insert",
        file=_ORDER_ENTRUSTED_ADMIN,
        method="saveOrUpdateEntrusted",
        snippet="containerAdminService.batchInsert(containerList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_container",
        kind="batch_insert",
        file=_ORDER_ENTRUSTED_PORTAL,
        method="saveOrUpdateEntrusted",
        snippet="containerPortalService.batchInsert(containerList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_container",
        kind="batch_insert",
        file=_ORDER_ENTRUSTED_ADMIN,
        method="generatePlanFromContract",
        snippet="containerAdminService.batchInsert(workPlanContainers);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_container",
        kind="save_or_update",
        file=_ENTRUSTED_ORDER_ADMIN,
        method="saveContainerItems",
        snippet="containerAdminService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_container",
        kind="batch_insert",
        file=_ORDER_WORK_PLAN_PORTAL,
        method="workDistribute",
        snippet="containerPortalService.batchInsert(containerList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_node",
        kind="save_or_update",
        file=_ENTRUSTED_ORDER_ADMIN,
        method="saveOrderNode",
        snippet="orderNodeAdminService.saveOrUpdate(orderNode);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_node",
        kind="save_or_update",
        file=_ORDER_ORDER_PORTAL,
        method="entrustedOrderSign",
        snippet="orderNodePortalService.saveOrUpdate(orderNode);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_node",
        kind="save_or_update",
        file=_ORDER_WORK_PLAN_ADMIN,
        method="save",
        snippet="orderNodeAdminService.saveOrUpdate(orderNode);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_booking_application",
        kind="save_or_update",
        file=_ORDER_BOOKING_BASIC,
        method="generateBookingData",
        snippet="dao.saveOrUpdate(bookingApplication);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_booking_application",
        kind="save_or_update",
        file=_ORDER_BOOKING_ADMIN,
        method="save",
        snippet="dao.saveOrUpdate(bookingApplicationAdminItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_booking_application",
        kind="save_or_update",
        file=_ORDER_BOOKING_PORTAL,
        method="save",
        snippet="dao.saveOrUpdate(bookingApplicationPortalItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_booking_application_confirm",
        kind="save_or_update",
        file=_ORDER_CONFIRM_ADMIN,
        method="saveOrUpdateInfo",
        snippet="this.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_attachment",
        kind="batch_insert",
        file=_ORDER_ATTACH_PORTAL,
        method="batchSave",
        snippet="dao.batchInsert(list);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_attachment",
        kind="save_or_update",
        file=_ORDER_ATTACH_BASIC,
        method="uploadAndSave",
        snippet="saveOrUpdate(attachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_file",
        kind="save_or_update",
        file=_ORDER_FILE,
        method="upload",
        snippet="dao.saveOrUpdate(entrustedOrderFile);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_outbound_order",
        kind="save_or_update",
        file=_ORDER_WMS,
        method="process",
        snippet="outboundOrderDao.saveOrUpdate(outboundOrder);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_outbound_order_detail",
        kind="save_or_update",
        file=_ORDER_WMS,
        method="syncDetails",
        snippet="outboundOrderDetailDao.saveOrUpdate(detail);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_outbound_entrusted_relation",
        kind="save_or_update",
        file=_ORDER_WMS,
        method="saveEntrustedRelation",
        snippet="outboundOrderEntrustedRelationDao.saveOrUpdate(relation);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_outbound_transport_relation",
        kind="save_or_update",
        file=_ORDER_TRANSPORT,
        method="bindLoadedTransport",
        snippet="outboundTransportRelationDao.saveOrUpdate(relation);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_order_container",
        kind="batch_insert",
        file=_ORDER_WORK_PLAN_ADMIN,
        method="save",
        snippet="containerAdminService.batchInsert(containers);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_route",
        kind="save_or_update",
        file=_BT_ROUTE,
        method="saveBtRoute",
        snippet="saveOrUpdate(btRoute);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_route_station",
        kind="save_or_update",
        file=_BT_ROUTE,
        method="syncRouteStations",
        snippet="btRouteStationDao.saveOrUpdate(station);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_daily_plan",
        kind="save_or_update",
        file=_BT_DAILY,
        method="saveReportPlan",
        snippet="saveOrUpdate(plan);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_daily_plan_box",
        kind="save_or_update",
        file=_BT_DAILY,
        method="saveBoxes",
        snippet="boxDao.saveOrUpdate(box);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_DEPARTURE,
        method="saveBtDeparturePlan",
        snippet="saveOrUpdate(departurePlan);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_TRAIN_PLAN,
        method="saveBtTrainPlanList",
        snippet="saveOrUpdate(plan);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_departure_plan_station",
        kind="save_or_update",
        file=_BT_DEPARTURE_STATION,
        method="syncPlanStations",
        snippet="dao.saveOrUpdate(station);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_departure_plan_station",
        kind="save_or_update",
        file=_BT_DEPARTURE_STATION,
        method="saveBtDeparturePlanStation",
        snippet="saveOrUpdate(station);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_departure_plan_daily_plan",
        kind="save_or_update",
        file=_BT_DEPARTURE_DAILY,
        method="saveRelation",
        snippet="saveOrUpdate(relation);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_departure_plan_change_record",
        kind="save_or_update",
        file=_BT_DEPARTURE_CHANGE,
        method="saveChangeRecord",
        snippet="saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_monthly_entrusted",
        kind="save_or_update",
        file=_BT_MONTHLY,
        method="save",
        snippet="saveOrUpdate(monthlyEntrusted);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_monthly_entrusted_supplement",
        kind="save_or_update",
        file=_BT_SUPPLEMENT,
        method="save",
        snippet="saveOrUpdate(supplement);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_waybill",
        kind="save_or_update",
        file=_BT_WAYBILL,
        method="saveDispatchedWaybill",
        snippet="saveOrUpdate(waybill);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_waybill_box",
        kind="save_or_update",
        file=_BT_WAYBILL,
        method="saveWaybillBoxes",
        snippet="waybillBoxDao.saveOrUpdate(box);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_waybill_voucher",
        kind="save_or_update",
        file=_BT_WAYBILL,
        method="saveVouchers",
        snippet="voucherService.saveOrUpdate(voucher);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_train_operation_tracking",
        kind="save_or_update",
        file=_BT_TRACKING,
        method="saveBtTrainOperationTracking",
        snippet="saveOrUpdate(operation);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_train_operation_log",
        kind="save_or_update",
        file=_BT_LOG,
        method="saveLog",
        snippet="saveOrUpdate(log);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_bt_train_operation_exception_record",
        kind="save_or_update",
        file=_BT_EXCEPTION,
        method="saveRecord",
        snippet="saveOrUpdate(record);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_expense",
        kind="save_or_update",
        file=_SETTLE_EXPENSE,
        method="save",
        snippet="saveOrUpdate(expense);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_expense_modify_log",
        kind="insert",
        file=_SETTLE_LOG,
        method="insertModifyLog",
        snippet="insert(modifyLog);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_bt_expense",
        kind="save_or_update",
        file=_SETTLE_BT_EXPENSE,
        method="save",
        snippet="saveOrUpdate(expense);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_bt_expense_modify_log",
        kind="insert",
        file=_SETTLE_BT_LOG,
        method="insertModifyLog",
        snippet="insert(modifyLog);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_payable_bill",
        kind="save_or_update",
        file=_SETTLE_PAYABLE,
        method="save",
        snippet="saveOrUpdate(payableBill);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_receivable_bill",
        kind="save_or_update",
        file=_SETTLE_RECEIVABLE,
        method="save",
        snippet="saveOrUpdate(receivableBill);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_receivable_bill",
        kind="save_or_update",
        file=_SETTLE_OP_FEE,
        method="generateBillingOrder",
        snippet="saveOrUpdate(receivableBill);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_payment_apply",
        kind="save_or_update",
        file=_SETTLE_APPLY,
        method="generatePaymentRequest",
        snippet="saveOrUpdate(paymentApply);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_payment_apply",
        kind="save_or_update",
        file=_SETTLE_APPLY,
        method="save",
        snippet="saveOrUpdate(paymentApply);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_payment_relation",
        kind="batch_insert",
        file=_SETTLE_APPLY,
        method="generatePaymentRequest",
        snippet="paymentRelationAdminService.batchInsert(paymentRelationList);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_payment_approval_history",
        kind="save_or_update",
        file=_SETTLE_APPLY,
        method="approve",
        snippet="paymentApplyHistoryAdminService.saveOrUpdate(approvalHistory);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_sales_invoice",
        kind="save_or_update",
        file=_SETTLE_INVOICE,
        method="save",
        snippet="saveOrUpdate(salesInvoice);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_prepayment",
        kind="save_or_update",
        file=_SETTLE_PREPAY,
        method="save",
        snippet="saveOrUpdate(prepayment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_prepayment_bill",
        kind="save_or_update",
        file=_SETTLE_PREPAY_BILL,
        method="calBillVerifyAmount",
        snippet="saveOrUpdate(prepaymentBill);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_owner_fund",
        kind="save_or_update",
        file=_SETTLE_FUND,
        method="save",
        snippet="saveOrUpdate(ownerFund);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_owner_fund_flow",
        kind="save_or_update",
        file=_SETTLE_FLOW,
        method="confirmReceipt",
        snippet="saveOrUpdate(ownerFundFlow);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_operation_fee",
        kind="save_or_update",
        file=_SETTLE_OP_FEE,
        method="saveOrUpdateReturnEntity",
        snippet="saveOrUpdate(operationFee);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_operation_fee_detail",
        kind="save_or_update",
        file=_SETTLE_OP_FEE,
        method="generateBillingOrder",
        snippet="dao.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_payment_confirmation",
        kind="save_or_update",
        file=_SETTLE_PAY_CONFIRM,
        method="save",
        snippet="saveOrUpdate(paymentConfirmation);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_payment_verification",
        kind="save_or_update",
        file=_SETTLE_PAY_VERIFY,
        method="save",
        snippet="saveOrUpdate(paymentVerificationItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_receipt_confirmation",
        kind="save_or_update",
        file=_SETTLE_RCV_CONFIRM,
        method="save",
        snippet="saveOrUpdate(receiptConfirmation);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_receipt_verification",
        kind="save_or_update",
        file=_SETTLE_RCV_VERIFY,
        method="save",
        snippet="saveOrUpdate(receiptVerificationItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_collection",
        kind="save_or_update",
        file=_SETTLE_COLLECTION,
        method="save",
        snippet="saveOrUpdate(precollection);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_advance_payment",
        kind="save_or_update",
        file=_SETTLE_ADVANCE,
        method="save",
        snippet="saveOrUpdate(advancePayment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_settlement_attachment",
        kind="save_or_update",
        file=_SETTLE_ATTACH,
        method="upload",
        snippet="dao.saveOrUpdate(settlementAttachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order",
        kind="save_or_update",
        file=_DECL_ORDER,
        method="save",
        snippet="saveOrUpdate(order);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_transport",
        kind="save_or_update",
        file=_DECL_TRANSPORT,
        method="save",
        snippet="saveOrUpdate(dbOrderTransport);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_declare",
        kind="save_or_update",
        file=_DECL_DECLARE,
        method="save",
        snippet="saveOrUpdate(dbOrderDeclare);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine",
        kind="save_or_update",
        file=_DECL_QUARANTINE,
        method="save",
        snippet="saveOrUpdate(orderQuarantine);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine_enterprise",
        kind="insert",
        file=_DECL_ENTERPRISE,
        method="batchSave",
        snippet="insert(orderQuarantineEnterprise);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_cargo",
        kind="save_or_update",
        file=_DECL_CARGO,
        method="batchSave",
        snippet="saveOrUpdate(orderCargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_cargo_attribute",
        kind="insert",
        file=_DECL_CARGO,
        method="batchSave",
        snippet="orderCargoAttributeBasicService.insert(orderCargoAttribute);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_container",
        kind="save_or_update",
        file=_DECL_CONTAINER,
        method="batchSave",
        snippet="saveOrUpdate(orderContainer);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_document",
        kind="save_or_update",
        file=_DECL_DOCUMENT,
        method="batchSave",
        snippet="saveOrUpdate(orderDocument);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_entrust",
        kind="save_or_update",
        file=_DECL_ENTRUST,
        method="save",
        snippet="return saveOrUpdate(entrust);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_attachment",
        kind="save_or_update",
        file=_DECL_ATTACH,
        method="save",
        snippet="saveOrUpdate(attachmentItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_commodity",
        kind="save_or_update",
        file=_DECL_COMMODITY,
        method="save",
        snippet="saveOrUpdate(commodityItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_commodity_catalog",
        kind="save_or_update",
        file=_DECL_CATALOG,
        method="saveOrUpdate",
        snippet="boolean b = dao.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_basic_information",
        kind="save_or_update",
        file=_DECL_BASIC_INFO,
        method="saveOrUpdate",
        snippet="dao.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_commodity_basic_data",
        kind="save_or_update",
        file=_DECL_BASIC_DATA,
        method="saveOrUpdate",
        snippet="dao.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_origin",
        kind="save_or_update",
        file=_DECL_ORIGIN,
        method="saveOrUpdate",
        snippet="dao.saveOrUpdate( item);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_interface_file_transfer_record",
        kind="save_or_update",
        file=_DECL_FILE,
        method="onMessage",
        snippet="fileTransferRecordBasicService.saveOrUpdate(fileTransferRecord);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order",
        kind="save_or_update",
        file=_DECL_ORDER_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order",
        kind="save_or_update",
        file=_DECL_ORDER_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order",
        kind="save_or_update",
        file=_DECL_ORDER,
        method="copy",
        snippet="saveOrUpdate(order);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_transport",
        kind="save_or_update",
        file=_DECL_TRANSPORT_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderTransportItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_transport",
        kind="save_or_update",
        file=_DECL_TRANSPORT_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderTransportItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_transport",
        kind="save_or_update",
        file=_DECL_ORDER,
        method="copy",
        snippet="orderTransportBasicService.saveOrUpdate(orderTransport);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_declare",
        kind="save_or_update",
        file=_DECL_DECLARE_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderDeclareItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_declare",
        kind="save_or_update",
        file=_DECL_DECLARE_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderDeclareItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_declare",
        kind="save_or_update",
        file=_DECL_ORDER,
        method="copy",
        snippet="orderDeclareBasicService.saveOrUpdate(orderDeclare);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine",
        kind="save_or_update",
        file=_DECL_QUARANTINE_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderQuarantineItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine",
        kind="save_or_update",
        file=_DECL_QUARANTINE_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderQuarantineItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine",
        kind="save_or_update",
        file=_DECL_ORDER,
        method="copy",
        snippet="orderQuarantineBasicService.saveOrUpdate(orderQuarantine);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine_enterprise",
        kind="save_or_update",
        file=_DECL_ENTERPRISE_ADMIN,
        method="save",
        snippet="saveOrUpdate(quarantineEnterpriseItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine_enterprise",
        kind="save_or_update",
        file=_DECL_ENTERPRISE_PORTAL,
        method="save",
        snippet="saveOrUpdate(quarantineEnterpriseItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine_enterprise",
        kind="save_or_update",
        file=_DECL_ORDER,
        method="copy",
        snippet="quarantineEnterpriseBasicService.saveOrUpdate(quarantineEnterprise);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_cargo",
        kind="save_or_update",
        file=_DECL_CARGO_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderCargoItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_cargo",
        kind="save_or_update",
        file=_DECL_CARGO_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderCargoItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_cargo",
        kind="save_or_update",
        file=_DECL_ORDER,
        method="copy",
        snippet="orderCargoBasicService.saveOrUpdate(orderCargo);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_cargo_attribute",
        kind="save_or_update",
        file=_DECL_ATTRIBUTE,
        method="batchSave",
        snippet="saveOrUpdate(orderCargoAttribute);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_cargo_attribute",
        kind="save_or_update",
        file=_DECL_ATTRIBUTE_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderCargoAttributeItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_cargo_attribute",
        kind="save_or_update",
        file=_DECL_ATTRIBUTE_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderCargoAttributeItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_cargo_attribute",
        kind="save_or_update",
        file=_DECL_ORDER,
        method="copy",
        snippet="orderCargoAttributeBasicService.saveOrUpdate(orderCargoAttribute);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_container",
        kind="save_or_update",
        file=_DECL_CONTAINER_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderContainerItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_container",
        kind="save_or_update",
        file=_DECL_CONTAINER_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderContainerItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_container",
        kind="save_or_update",
        file=_DECL_ORDER,
        method="copy",
        snippet="orderContainerBasicService.saveOrUpdate(orderContainer);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_document",
        kind="save_or_update",
        file=_DECL_DOCUMENT_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderDocumentItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_document",
        kind="save_or_update",
        file=_DECL_DOCUMENT_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderDocumentItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_order_document",
        kind="save_or_update",
        file=_DECL_ORDER,
        method="copy",
        snippet="orderDocumentBasicService.saveOrUpdate(orderDocument);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_entrust",
        kind="save_or_update",
        file=_DECL_ENTRUST,
        method="copy",
        snippet="saveOrUpdate(entrust);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_attachment",
        kind="save_or_update",
        file=_DECL_ATTACH_BASIC,
        method="storeFile",
        snippet="saveOrUpdate(attachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_attachment",
        kind="save_or_update",
        file=_DECL_ATTACH_BASIC,
        method="uploadAndSave",
        snippet="saveOrUpdate(attachment);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_attachment",
        kind="save_or_update",
        file=_DECL_ATTACH_PORTAL,
        method="save",
        snippet="saveOrUpdate(attachmentItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_attachment",
        kind="save_or_update",
        file=_DECL_ATTACH_PORTAL,
        method="copy",
        snippet="saveOrUpdate(attachmentPortalItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_commodity",
        kind="save_or_update",
        file=_DECL_COMMODITY_PORTAL,
        method="save",
        snippet="saveOrUpdate(commodityItem);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_commodity",
        kind="batch_insert",
        file=_DECL_COMMODITY,
        method="saveOrUpdateImportItem",
        snippet="insertNum = dao.batchInsert(toInsertItems);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_basic_information",
        kind="batch_insert",
        file=_DECL_BASIC_INFO,
        method="saveOrUpdateImportItem",
        snippet="insertNum = dao.batchInsert(toInsertItems);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_basic_information",
        kind="batch_insert",
        file=_DECL_BASIC_INFO,
        method="saveImportItem",
        snippet="insertNum = dao.batchInsert(toInsertItems);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_commodity_basic_data",
        kind="batch_insert",
        file=_DECL_BASIC_DATA,
        method="validateAndSaveImportCommodityBasicData",
        snippet="insertNum = dao.batchInsert(toInsertItems);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_origin",
        kind="batch_insert",
        file=_DECL_ORIGIN,
        method="saveOrUpdateImportItem",
        snippet="insertNum = dao.batchInsert(toInsertItems);",
    ),
    SeedWrite(
        table=f"{MTP}.cs_dsly_declaration_interface_file_transfer_record",
        kind="save_or_update",
        file=_DECL_FILE_GOODS,
        method="onMessage",
        snippet="fileTransferRecordBasicService.saveOrUpdate(fileTransferRecord);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="save_or_update",
        file=_MEMBER_USER,
        method="saveOrUpdate",
        snippet="saveOrUpdate(userInfo);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="save_or_update",
        file=_MEMBER_USER,
        method="saveOrUpdateCustomsDeclarant",
        snippet="saveOrUpdate(declarantUserInfo);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="save_or_update",
        file=_MEMBER_USER,
        method="createAndSaveUserInfo",
        snippet="saveOrUpdate(newUserInfo);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="save_or_update",
        file=_MEMBER_USER_PORTAL,
        method="createAndSaveUserInfo",
        snippet="saveOrUpdate(newUserInfo);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="save_or_update",
        file=_MEMBER_USER_PORTAL,
        method="ensureLoginUserInfo",
        snippet="saveOrUpdate(userInfo);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="save_or_update",
        file=_MEMBER_USER_PORTAL,
        method="saveOrUpdateEnterpriseUserInfo",
        snippet="saveOrUpdate(userInfo);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="save_or_update",
        file=_MEMBER_USER_PORTAL,
        method="saveDriver",
        snippet="saveOrUpdate(driverUserInfo);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="save_or_update",
        file=_MEMBER_USER_PORTAL,
        method="saveUserInfo",
        snippet="saveOrUpdate(userInfoPortalItem);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="save_or_update",
        file=_MEMBER_USER,
        method="createAndSaveUserAuthInfo",
        snippet="userAuthInfoService.saveOrUpdate(mainRoleAuth);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="save_or_update",
        file=_MEMBER_USER,
        method="saveOrUpdateCustomsDeclarant",
        snippet="userAuthInfoService.saveOrUpdate(authInfo);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="save_or_update",
        file=_MEMBER_USER,
        method="createAndSaveUserInfo",
        snippet="userAuthInfoService.saveOrUpdate(newAgentInfo);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="insert",
        file=_MEMBER_USER,
        method="updateAgentStatus",
        snippet="userAuthInfoService.insert(userAuthInfo);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="save_or_update",
        file=_MEMBER_USER_PORTAL,
        method="createAndSaveUserAuthInfo",
        snippet="userAuthInfoPortalService.saveOrUpdate(mainRoleAuth);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="save_or_update",
        file=_MEMBER_USER_PORTAL,
        method="processBidderAuth",
        snippet="userAuthInfoPortalService.saveOrUpdate(bidderAuthInfo);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="save_or_update",
        file=_MEMBER_USER_PORTAL,
        method="handleShipperAgentRole",
        snippet="userAuthInfoPortalService.saveOrUpdate(newAgentInfo);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="batch_insert",
        file=_MEMBER_USER_PORTAL,
        method="processCarrierAuth",
        snippet="userAuthInfoPortalService.batchInsert(toInsert);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="batch_insert",
        file=_MEMBER_USER_PORTAL,
        method="processPersonalAuth",
        snippet="userAuthInfoPortalService.batchInsert(toInsert);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="batch_insert",
        file=_MEMBER_USER_PORTAL,
        method="persistAuthInfoChanges",
        snippet="userAuthInfoPortalService.batchInsert(toInsert);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="batch_insert",
        file=_MEMBER_USER_PORTAL,
        method="saveEnterpriseAuthInfo",
        snippet="userAuthInfoPortalService.batchInsert(toInsert);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="save_or_update",
        file=_MEMBER_USER_PORTAL,
        method="saveDriver",
        snippet="return userAuthInfoPortalService.saveOrUpdate(userAuthInfoPortalItem);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="batch_insert",
        file=_MEMBER_USER_PORTAL,
        method="saveUserInfo",
        snippet="userAuthInfoPortalService.batchInsert(authInfoPortalItemList);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_user_identity_auth_detail",
        kind="batch_insert",
        file=_MEMBER_AUTH_DETAIL,
        method="saveOrUpdateBySnapshot",
        snippet="batchInsert(toInsert);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_contract",
        kind="save_or_update",
        file=_MEMBER_CONTRACT,
        method="save",
        snippet="saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_contract_operation",
        kind="save_or_update",
        file=_MEMBER_CONTRACT_OP,
        method="save",
        snippet="saveOrUpdate(contractOperationAdminItem);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_contract_quote_info",
        kind="batch_insert",
        file=_MEMBER_CONTRACT,
        method="save",
        snippet="contractQuoteInfoAdminService.batchInsert(contractQuoteInfos);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_contract_quote_info",
        kind="batch_insert",
        file=_MEMBER_CONTRACT,
        method="syncContractInfo",
        snippet="contractQuoteInfoAdminService.batchInsert(quoteInfoList);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_shipper_level",
        kind="save_or_update",
        file=_MEMBER_LEVEL,
        method="save",
        snippet="dao.saveOrUpdate(shipperLevelItem);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_shipper_level_history",
        kind="save_or_update",
        file=_MEMBER_LEVEL,
        method="save",
        snippet="shipperLevelHistoryDao.saveOrUpdate(shipperLevelHistory);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_shipper_level_history",
        kind="save_or_update",
        file=_MEMBER_LEVEL_HISTORY_CTRL,
        method="save",
        snippet="shipperLevelHistoryService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_attachment",
        kind="save_or_update",
        file=_MEMBER_ATTACH,
        method="uploadByContractId",
        snippet="dao.saveOrUpdate(attachment);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_attachment",
        kind="save_or_update",
        file=_MEMBER_LEVEL,
        method="save",
        snippet="attachmentDao.saveOrUpdate(attachmentAdminItem);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_attachment",
        kind="batch_insert",
        file=_MEMBER_ATTACH_PORTAL,
        method="batchSave",
        snippet="dao.batchInsertToSqlExecution(list);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_invoice",
        kind="save_or_update",
        file=_MEMBER_INVOICE,
        method="saveOrEdit",
        snippet="return dao.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_message_recipient",
        kind="save_or_update",
        file=_MEMBER_MSG,
        method="saveOrUpdateMessageRecipient",
        snippet="dao.saveOrUpdate(recipient);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_entrusted_order_complain",
        kind="save_or_update",
        file=_MEMBER_COMPLAIN,
        method="save",
        snippet="dao.saveOrUpdate(entrustedOrderComplainPortalItem);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_member_entrusted_order_evaluation",
        kind="save_or_update",
        file=_MEMBER_EVAL_CTRL,
        method="save",
        snippet="entrustedOrderEvaluationPortalService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_kpi",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveKpi",
        snippet="kpiService.saveOrUpdate(entity);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_cargo_summary",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveSummary",
        snippet="cargoSummaryService.saveOrUpdate(entity);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_cargo_category",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveCategories",
        snippet="cargoCategoryService.saveOrUpdate(entity);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_enterprise_rank",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveDimension",
        snippet="enterpriseRankService.saveOrUpdate(entity);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_city_flow",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveCityFlow",
        snippet="cityFlowService.saveOrUpdate(entity);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_city_flow_cargo",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveCityFlowCargo",
        snippet="cityFlowCargoService.saveOrUpdate(entity);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_map_flow",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveMapFlow",
        snippet="mapFlowService.saveOrUpdate(entity);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_timeliness_route",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveTimeliness",
        snippet="timelinessRouteService.saveOrUpdate(entity);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_station_turnover",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveTurnover",
        snippet="stationTurnoverService.saveOrUpdate(entity);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_ontime_summary",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveOnTime",
        snippet="ontimeSummaryService.saveOrUpdate(summary);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_ontime_route",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveOnTime",
        snippet="ontimeRouteService.saveOrUpdate(entity);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_congestion",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveAnomaly",
        snippet="congestionService.saveOrUpdate(entity);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_accident",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveAnomaly",
        snippet="accidentService.saveOrUpdate(entity);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_kpi",
        kind="save_or_update",
        file=_COCKPIT_KPI_CTRL,
        method="save",
        snippet="cockpitKpiService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_cargo_summary",
        kind="save_or_update",
        file=_COCKPIT_SUMMARY_CTRL,
        method="save",
        snippet="cockpitCargoSummaryService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_cargo_category",
        kind="save_or_update",
        file=_COCKPIT_CATEGORY_CTRL,
        method="save",
        snippet="cockpitCargoCategoryService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_enterprise_rank",
        kind="save_or_update",
        file=_COCKPIT_ENTERPRISE_CTRL,
        method="save",
        snippet="cockpitEnterpriseRankService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_city_flow",
        kind="save_or_update",
        file=_COCKPIT_CITY_FLOW_CTRL,
        method="save",
        snippet="cockpitCityFlowService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_city_flow_cargo",
        kind="save_or_update",
        file=_COCKPIT_CITY_CARGO_CTRL,
        method="save",
        snippet="cockpitCityFlowCargoService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_map_flow",
        kind="save_or_update",
        file=_COCKPIT_MAP_CTRL,
        method="save",
        snippet="cockpitMapFlowService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_timeliness_route",
        kind="save_or_update",
        file=_COCKPIT_TIMELINESS_CTRL,
        method="save",
        snippet="cockpitTimelinessRouteService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_station_turnover",
        kind="save_or_update",
        file=_COCKPIT_STATION_CTRL,
        method="save",
        snippet="cockpitStationTurnoverService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_ontime_summary",
        kind="save_or_update",
        file=_COCKPIT_ONTIME_SUMMARY_CTRL,
        method="save",
        snippet="cockpitOntimeSummaryService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_ontime_route",
        kind="save_or_update",
        file=_COCKPIT_ONTIME_ROUTE_CTRL,
        method="save",
        snippet="cockpitOntimeRouteService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_congestion",
        kind="save_or_update",
        file=_COCKPIT_CONGESTION_CTRL,
        method="save",
        snippet="cockpitCongestionService.saveOrUpdate(item);",
    ),
    SeedWrite(
        table=f"{PORTAL}.cs_portal_cockpit_accident",
        kind="save_or_update",
        file=_COCKPIT_ACCIDENT_CTRL,
        method="save",
        snippet="cockpitAccidentService.saveOrUpdate(item);",
    ),
)


SEED_UPDATES: tuple[SeedUpdate, ...] = (
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_address",
        kind="save_or_update",
        file=_BASIC_ADMIN,
        method="save",
        snippet="saveOrUpdate(addressAdminItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_address",
        kind="save_or_update",
        file=_BASIC_PORTAL,
        method="save",
        snippet="saveOrUpdate(addressAdminItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_carrier_order",
        kind="update",
        file=_CARRIER_PORTAL,
        method="batchDispatchOrder",
        snippet=(
            "carrierOrder.setScheduledQuantity(carrierScheduledQuantity);\n"
            "carrierOrderDao.update(carrierOrder);"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_cargo",
        kind="batch_update",
        file=_CARRIER_PORTAL,
        method="batchDispatchOrder",
        snippet=(
            "if(CollUtil.isNotEmpty(updateCargoList)) {\n"
            "    cargoDao.batchUpdate(updateCargoList);\n"
            "}\n"
            "carrierCargo.setScheduledQuantity(dispatchScheduleQuantity);\n"
            "cargoDao.update(carrierCargo);"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_cargo",
        kind="update",
        file=_DISPATCH_PORTAL,
        method="redispatch",
        snippet=(
            "cargoDao.update(carrierCargo);//更新承运订单调度量，未调度量\n"
            "cargoDao.update(dispatchCargo);//更新运输订单计划量"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_dispatch_order",
        kind="batch_update",
        file=_CARRIER_PORTAL,
        method="batchDispatchOrder",
        snippet=(
            "if(CollUtil.isNotEmpty(updateDispatchOrderList)) {\n"
            "    dispatchOrderDao.batchUpdate(updateDispatchOrderList);\n"
            "}"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_dispatch_order",
        kind="update",
        file=_DISPATCH_PORTAL,
        method="redispatch",
        snippet="update(dispatchOrder);//更新运单信息",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_dispatch_order",
        kind="update",
        file=_DISPATCH_PORTAL,
        method="load",
        snippet=(
            "setDispatchOrderStatus(dispatchOrder, HighwayDispatchActionStatusEnum.LOAD);\n"
            "update(dispatchOrder);"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_dispatch_order",
        kind="update",
        file=_DISPATCH_PORTAL,
        method="modifyLoadInfo",
        snippet=(
            "setDispatchOrderStatus(dispatchOrder, HighwayDispatchActionStatusEnum.MODIFY_LOAD);\n"
            "update(dispatchOrder);"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_dispatch_order",
        kind="update",
        file=_DISPATCH_PORTAL,
        method="unload",
        snippet=(
            "setDispatchOrderStatus(dispatchOrder, HighwayDispatchActionStatusEnum.UNLOAD);\n"
            "update(dispatchOrder);"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_dispatch_order",
        kind="update",
        file=_DISPATCH_PORTAL,
        method="modifyUnloadInfo",
        snippet=(
            "setDispatchOrderStatus(dispatchOrder, HighwayDispatchActionStatusEnum.MODIFY_UNLOAD);\n"
            "update(dispatchOrder);"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_dispatch_order",
        kind="update",
        file=_DISPATCH_ADMIN,
        method="sign",
        snippet=(
            "setDispatchOrderStatus(dispatchOrder, HighwayDispatchActionStatusEnum.SIGNED);\n"
            "update(dispatchOrder);"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_dispatch_order",
        kind="save_or_update",
        file=_RISK_TASK,
        method="applyOrderRiskResult",
        snippet=(
            "dispatchOrder.setRiskEventTime(eventTime);\n"
            "dispatchOrder.setRiskCheckedTime(new Date());\n"
            "dispatchOrderDao.saveOrUpdate(dispatchOrder);"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_dispatch_order",
        kind="save_or_update",
        file=_RISK_TASK,
        method="enqueueDispatchEvaluations",
        snippet=(
            "dispatchOrder.setRiskCheckedTime(null);\n"
            "dispatchOrderDao.saveOrUpdate(dispatchOrder);\n"
            "createTask(dispatchOrder.getDispatchOrderNo(), eventTime, payloadJson,"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_dispatch_order",
        kind="save_or_update",
        file=_RISK_TASK,
        method="markOrderPending",
        snippet=(
            "dispatchOrder.setRiskRequestId(requestId);\n"
            "dispatchOrder.setRiskEventTime(eventTime);\n"
            "dispatchOrder.setRiskCheckedTime(null);\n"
            "dispatchOrderDao.saveOrUpdate(dispatchOrder);"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_dispatch_order",
        kind="save_or_update",
        file=_RISK_TASK,
        method="updateOrderRiskResult",
        snippet=(
            "dispatchOrder.setRiskEvaluationNo(result.getEvaluationNo());\n"
            "dispatchOrder.setRiskCheckedTime(new Date());\n"
            "dispatchOrderDao.saveOrUpdate(dispatchOrder);\n"
            "if (TRIGGER_DISPATCH.equals(task.getTriggerNode())"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_inbound_order",
        kind="update",
        file=_INBOUND_CREATE,
        method="createAndPublish",
        snippet=(
            "inboundOrder.setPushStatus(\n"
            "        success ? PUSH_STATUS_PENDING : PUSH_STATUS_FAILED);\n"
            "inboundOrderDao.update(inboundOrder);"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_inbound_order",
        kind="update",
        file=_INBOUND_ADMIN,
        method="retry",
        snippet="inboundOrderDao.update(inboundOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_carrier_settlement",
        kind="update",
        file=_SETTLEMENT_ADMIN,
        method="changeCarrierUpdate",
        snippet=(
            "Settlement settlement = GenericBeanConverter.convert("
            "settlementQuery, Settlement.class);\n"
            "settlementDao.update(settlement);"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_cargo",
        kind="update",
        file=_SHIPPING_PORTAL,
        method="batchDispatchOrder",
        snippet="cargoDao.update(carrierOrderCargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_cargo",
        kind="update",
        file=_CARGO_BASIC,
        method="setLoadQuantity",
        snippet=("update(dispatchCargo);\nupdate(carrierCargo);"),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_cargo",
        kind="update",
        file=_CARGO_BASIC,
        method="setCargoQuantity",
        snippet=("update(dispatchCargo);\nupdate(carrierCargo);"),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_cargo",
        kind="update",
        file=_CARGO_BASIC,
        method="modifyCargoQuantity",
        snippet=("update(dispatchCargo);\nupdate(carrierCargo);"),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_carrier_order",
        kind="update",
        file=_CARRIER_ADMIN,
        method="withdrawCarrierOrder",
        snippet="dao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_carrier_order",
        kind="update",
        file=_CARRIER_ADMIN,
        method="changeCarrierOrderInfo",
        snippet="update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_carrier_order",
        kind="update",
        file=_CARRIER_ADMIN,
        method="forceCloseOrder",
        snippet="dao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_carrier_order",
        kind="update",
        file=_DISPATCH_PORTAL,
        method="operateUpdateCarrierOrderStatus",
        snippet=(
            "setStatus(carrierOrder, newStatus);\n"
            "if(carrierChange){\n"
            "    carrierOrderDao.update(carrierOrder);\n"
            "}"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_carrier_order",
        kind="update",
        file=_DISPATCH_PORTAL,
        method="redispatch",
        snippet=(
            "boolean carrierChange = dispatchSetCarrierOrderStatus("
            "carrierOrder, carrierCargo, dispatchOrders);\n"
            "if (carrierChange) {\n"
            "    carrierOrderDao.update(carrierOrder);\n"
            "}"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_carrier_order",
        kind="update",
        file=_DISPATCH_ADMIN,
        method="sign",
        snippet=(
            "carrierOrder.setStatus(HighwayCarrierOrderStatusEnum.COMPLETED.getCode());\n"
            "carrierOrderDao.update(carrierOrder);"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_inbound_order",
        kind="update",
        file=_WMS_SYNC,
        method="processReceipt",
        snippet="inboundOrderDao.update(inboundOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_inbound_order",
        kind="update",
        file=_WMS_SYNC,
        method="processOrderStatus",
        snippet="inboundOrderDao.update(inboundOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_inbound_order",
        kind="update",
        file=_WMS_SYNC,
        method="processAcceptResult",
        snippet="inboundOrderDao.update(inboundOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_inbound_order_cargo",
        kind="update",
        file=_WMS_SYNC,
        method="processReceipt",
        snippet="inboundOrderCargoDao.update(cargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_park_appointment",
        kind="update",
        file=_PARK_PORTAL,
        method="edit",
        snippet="update(latestAppointment);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_park_appointment",
        kind="update",
        file=_PARK_PORTAL,
        method="updateAuditStatus",
        snippet="update(appointment);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_park_appointment",
        kind="update",
        file=_PARK_PORTAL,
        method="updateAccessTime",
        snippet=("if (changed) {\n    update(appointment);\n}"),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_container",
        kind="update",
        file=_CONTAINER_PORTAL,
        method="modifyByLoad",
        snippet="update(first);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_highway_attachment",
        kind="save_or_update",
        file=_ATTACHMENT_ADMIN_CONTROLLER,
        method="saveOrUpdate",
        snippet="attachmentAdminService.saveOrUpdate(carrierAttachmentAdminItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_cargo",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="batchDispatchOrderGt",
        snippet="cargoDao.update(cargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_cargo",
        kind="update",
        file=_RW_CARRIER_BASIC,
        method="batchDispatchOrder",
        snippet="cargoDao.update(cargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_cargo",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="redispatch",
        snippet="cargoDao.update(dispatchCargo);//更新运输订单计划量",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_cargo",
        kind="update",
        file=_RW_CARGO_BASIC,
        method="setCargoQuantity",
        snippet="this.update(dispatchCargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_cargo",
        kind="update",
        file=_RW_CARGO_BASIC,
        method="modifyCargoQuantity",
        snippet="update(dispatchCargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_carrier_order",
        kind="update",
        file=_RW_CARRIER_ADMIN,
        method="withdrawCarrierOrder",
        snippet="dao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_carrier_order",
        kind="update",
        file=_RW_CARRIER_ADMIN,
        method="changeCarrierOrderInfo",
        snippet="update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_carrier_order",
        kind="update",
        file=_RW_CARRIER_ADMIN,
        method="forceCloseOrder",
        snippet="dao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_carrier_order",
        kind="update",
        file=_RW_CARRIER_BASIC,
        method="batchDispatchOrder",
        snippet="dao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_carrier_order",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="operateUpdateCarrierOrderStatus",
        snippet="carrierOrderDao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_carrier_order",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="sign",
        snippet="carrierOrderDao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_carrier_order",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="redispatch",
        snippet="carrierOrderDao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_carrier_order",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="batchDispatchOrderGt",
        snippet="carrierOrderDao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_carrier_order",
        kind="update",
        file=_RW_DISPATCH_PORTAL,
        method="operateUpdateCarrierOrderStatus",
        snippet="carrierOrderDao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_carrier_order",
        kind="update",
        file=_RW_DISPATCH_ADMIN,
        method="operateUpdateCarrierOrderStatus",
        snippet="carrierOrderDao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_carrier_order",
        kind="update",
        file=_RW_DISPATCH_ADMIN,
        method="updateCarrierOrderStatus",
        snippet="carrierOrderDao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_order",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="load",
        snippet="this.update(dispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_order",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="modifyLoadInfo",
        snippet="this.update(dispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_order",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="unload",
        snippet="this.update(dispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_order",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="modifyUnloadInfo",
        snippet="this.update(dispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_order",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="sign",
        snippet="this.update(dispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_order",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="depart",
        snippet="update(dispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_order",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="arrive",
        snippet="update(dispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_order",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="redispatch",
        snippet="this.update(dispatchOrder);//更新运单信息",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_order",
        kind="update",
        file=_RW_DISPATCH_BASIC,
        method="batchDispatchOrderGt",
        snippet="dao.update(dbDispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_order",
        kind="update",
        file=_RW_CARRIER_BASIC,
        method="batchDispatchOrder",
        snippet="dispatchOrderDao.update(dbDispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_order",
        kind="update",
        file=_RW_DISPATCH_ADMIN,
        method="processDisptachRecords",
        snippet="dao.update(order);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_carrier_settlement",
        kind="update",
        file=_RW_SETTLEMENT_ADMIN,
        method="changeCarrierUpdate",
        snippet="railwayCarrierSettlementDao.update(settlement);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_order_line",
        kind="batch_update",
        file=_RW_DISPATCH_BASIC,
        method="batchSaveOrUpdateLine",
        snippet="dispatchOrderLineBasicService.batchUpdate(updateStationList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_order_line",
        kind="batch_update",
        file=_RW_DISPATCH_ADMIN,
        method="processDispatchOrderLines",
        snippet="dispatchOrderLineAdminService.batchUpdate(lineListUpdate);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_manifest",
        kind="batch_update",
        file=_RW_DISPATCH_ADMIN,
        method="updateOrCreateManifest",
        snippet="dispatchManifestAdminService.batchUpdate(manifestListUpdate);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_manifest",
        kind="save_or_update",
        file=_RW_MANIFEST_BASIC,
        method="saveDispatchManifest",
        snippet="dao.saveOrUpdate(dispatchManifest);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_dispatch_record",
        kind="batch_update",
        file=_RW_DISPATCH_ADMIN,
        method="processDisptachRecords",
        snippet="recordAdminService.batchUpdate(recordListUpdate);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_railway_daily_plan",
        kind="save_or_update",
        file=_RW_DISPATCH_ADMIN,
        method="processTraceResult",
        snippet="railwayDailyPlanDao.saveOrUpdate(dailyPlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_cargo",
        kind="update",
        file=_SHIPPING_PORTAL,
        method="updateDispatchCargo",
        snippet="cargoDao.update(dispatchCargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_cargo",
        kind="update",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="unload",
        snippet="cargoDao.update(cargoDaoByCarrierOrderNo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_cargo",
        kind="update",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="redispatch",
        snippet="cargoDao.update(updateCarrierCargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_cargo",
        kind="update",
        file=_SHIPPING_CARGO_BASIC,
        method="setCargoQuantity",
        snippet="update(dispatchCargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_cargo",
        kind="update",
        file=_SHIPPING_CARGO_BASIC,
        method="modifyCargoQuantity",
        snippet="update(dispatchCargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_cargo",
        kind="update",
        file=_SHIPPING_DISPATCH_ADMIN,
        method="sign",
        snippet="cargoDao.update(dispatchCargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_carrier_order",
        kind="update",
        file=_SHIPPING_ADMIN,
        method="withdrawCarrierOrder",
        snippet="dao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_carrier_order",
        kind="update",
        file=_SHIPPING_ADMIN,
        method="changeCarrierOrderInfo",
        snippet="update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_carrier_order",
        kind="update",
        file=_SHIPPING_ADMIN,
        method="forceCloseOrder",
        snippet="dao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_carrier_order",
        kind="update",
        file=_SHIPPING_PORTAL,
        method="batchDispatchOrder",
        snippet="dao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_carrier_order",
        kind="update",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="redispatch",
        snippet="carrierOrderDao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_carrier_order",
        kind="update",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="operateUpdateCarrierOrderStatus",
        snippet="carrierOrderDao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_carrier_order",
        kind="update",
        file=_SHIPPING_DISPATCH_ADMIN,
        method="sign",
        snippet="carrierOrderDao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_carrier_order",
        kind="update",
        file=_SHIPPING_DISPATCH_ADMIN,
        method="operateUpdateCarrierOrderStatus",
        snippet="carrierOrderDao.update(carrierOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_dispatch_order",
        kind="update",
        file=_SHIPPING_PORTAL,
        method="updateDispatchOrderInfo",
        snippet="dispatchOrderDao.update(dbDispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_dispatch_order",
        kind="update",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="load",
        snippet="update(dispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_dispatch_order",
        kind="update",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="modifyLoadInfo",
        snippet="update(dispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_dispatch_order",
        kind="update",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="unload",
        snippet="update(dispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_dispatch_order",
        kind="update",
        file=_SHIPPING_DISPATCH_PORTAL,
        method="redispatch",
        snippet="update(dispatchOrder);//更新运单信息",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_dispatch_order",
        kind="update",
        file=_SHIPPING_DISPATCH_ADMIN,
        method="sign",
        snippet="update(dispatchOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_carrier_settlement",
        kind="update",
        file=_SHIPPING_SETTLEMENT_BASIC,
        method="changeCarrierUpdate",
        snippet="dao.update(settlement);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_dispatch_manifest",
        kind="save_or_update",
        file=_SHIPPING_MANIFEST_ADMIN_CONTROLLER,
        method="save",
        snippet="dispatchManifestAdminService.saveOrUpdate(dispatchManifest);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_shipping_attachment",
        kind="save_or_update",
        file=_SHIPPING_ATTACHMENT_ADMIN_CONTROLLER,
        method="saveOrUpdate",
        snippet=("attachmentAdminService.saveOrUpdate(shippingCarrierMemberAttachmentAdminItem);"),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_cargo",
        kind="save_or_update",
        file=_CARGO_ADMIN,
        method="saveCargo",
        snippet="dao.saveOrUpdate(cargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_cargo",
        kind="save_or_update",
        file=_CARGO_PORTAL,
        method="saveCargo",
        snippet="saveOrUpdate(cargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_cargo",
        kind="batch_update",
        file=_CARGO_BASIC_SVC,
        method="syncGoodsAuditStatus",
        snippet="return batchUpdate(cargoList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_cargo",
        kind="batch_update",
        file=_CARGO_BASIC_SVC,
        method="syncWmsSkuPackage",
        snippet="return batchUpdate(changedCargoList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_cargo",
        kind="update",
        file=_CARGO_CATEGORY_ADMIN,
        method="changeDisable",
        snippet="updateCargoStatusByCategoryIds(idList, YesNoConstant.NO);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_cargo_category",
        kind="save_or_update",
        file=_CARGO_CATEGORY_ADMIN,
        method="saveCargoCategory",
        snippet="saveOrUpdate(cargoCategory);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_cargo_category",
        kind="save_or_update",
        file=_CARGO_CATEGORY_PORTAL_CTRL,
        method="save",
        snippet="cargoCategoryPortalService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_cargo_category",
        kind="update",
        file=_CARGO_CATEGORY_ADMIN,
        method="changeEnable",
        snippet="updateCategoryStatus(idList, YesNoConstant.YES);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_cargo_category",
        kind="update",
        file=_CARGO_CATEGORY_ADMIN,
        method="changeDisable",
        snippet="updateCategoryStatus(idList, YesNoConstant.NO);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_cargo_base_price_config",
        kind="save_or_update",
        file=_PRICE_BASIC,
        method="save",
        snippet="saveOrUpdate(basePriceConfig);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_business_info",
        kind="save_or_update",
        file=_BUSINESS_ADMIN,
        method="save",
        snippet="saveOrUpdate(business);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_business_info",
        kind="save_or_update",
        file=_BUSINESS_PORTAL,
        method="save",
        snippet="saveOrUpdate(businessItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_expense_config",
        kind="save_or_update",
        file=_EXPENSE_ADMIN,
        method="save",
        snippet="saveOrUpdate(expenseConfig);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_expense_config",
        kind="save_or_update",
        file=_EXPENSE_PORTAL,
        method="save",
        snippet="saveOrUpdate(expenseConfigItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_expense_config",
        kind="batch_update",
        file=_EXPENSE_ADMIN,
        method="changeEnable",
        snippet="batchUpdate(expenseConfigList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_expense_config",
        kind="batch_update",
        file=_EXPENSE_ADMIN,
        method="changeDisable",
        snippet="batchUpdate(expenseConfigList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_billing_template",
        kind="save_or_update",
        file=_TEMPLATE_ADMIN,
        method="save",
        snippet="saveOrUpdate(templateItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_billing_template",
        kind="save_or_update",
        file=_TEMPLATE_PORTAL,
        method="save",
        snippet="saveOrUpdate(templateItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_billing_template",
        kind="update",
        file=_TEMPLATE_ADMIN,
        method="modifyRelateContractCount",
        snippet="update(thisTemplate);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_site_fee_item",
        kind="save_or_update",
        file=_SITE_FEE_ITEM_CTRL,
        method="save",
        snippet="siteFeeItemService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_site_fee_item_range",
        kind="save_or_update",
        file=_SITE_FEE_RANGE_CTRL,
        method="save",
        snippet="siteFeeItemRangeService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_vehicle",
        kind="save_or_update",
        file=_VEHICLE_BASIC,
        method="save",
        snippet="saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_driver_info",
        kind="save_or_update",
        file=_DRIVER_INFO,
        method="changeEnable",
        snippet="saveOrUpdate(driverInfo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_driver_info",
        kind="save_or_update",
        file=_DRIVER_INFO,
        method="changeDisable",
        snippet="saveOrUpdate(driverInfo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_ship",
        kind="save_or_update",
        file=_SHIP_ADMIN_CTRL,
        method="save",
        snippet="shipAdminService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_ship",
        kind="save_or_update",
        file=_SHIP_PORTAL_CTRL,
        method="save",
        snippet="shipPortalService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_ship_owner",
        kind="save_or_update",
        file=_SHIP_OWNER_ADMIN_CTRL,
        method="page",
        snippet="shipOwnerAdminService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_ship_owner",
        kind="save_or_update",
        file=_SHIP_OWNER_PORTAL_CTRL,
        method="save",
        snippet="shipOwnerPortalService.saveOrUpdate(shipOwner);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_port",
        kind="save_or_update",
        file=_PORT_ADMIN_SVC,
        method="savePort",
        snippet="dao.saveOrUpdate(port);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_basic_outbound_box",
        kind="update",
        file=_OUTBOUND_BOX_SYNC,
        method="process",
        snippet="outboundBoxDao.update(outboundBox);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="saveRouteDetails",
        snippet="dao.saveOrUpdate(route);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="validateImportData",
        snippet="this.saveOrUpdate(routeAdminItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="saveRouteRailway",
        snippet="dao.saveOrUpdate(route);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route",
        kind="batch_update",
        file=_LINE_ROUTE_ADMIN,
        method="recordAuditRecord",
        snippet="this.batchUpdate(updateRouteList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route",
        kind="batch_update",
        file=_LINE_ROUTE_ADMIN,
        method="updateQuote",
        snippet="batchUpdate(routeUpdateList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route",
        kind="batch_update",
        file=_LINE_ROUTE_ADMIN,
        method="batchSaveRouteRailway",
        snippet="dao.batchUpdate(routesToSave);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route",
        kind="save_or_update",
        file=_LINE_ROUTE_PORTAL,
        method="saveRouteDetails",
        snippet="dao.saveOrUpdate(route);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="createReverseRoute",
        snippet=(
            "reverseRoute.setAddressId(reverseAddressResult.getId());\n"
            "        dao.saveOrUpdate(reverseRoute);"
        ),
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_product",
        kind="save_or_update",
        file=_LINE_ROUTE_PRODUCT_ADMIN,
        method="saveOrUpdateInfo",
        snippet="this.saveOrUpdate(routeProduct);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_product",
        kind="batch_update",
        file=_LINE_ROUTE_PRODUCT_ADMIN,
        method="recordAuditRecord",
        snippet="this.batchUpdate(updateRouteList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_product",
        kind="save_or_update",
        file=_LINE_ROUTE_PRODUCT_BASIC,
        method="saveOrUpdateInfo",
        snippet="this.saveOrUpdate(routeProduct);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_product",
        kind="update",
        file=_LINE_ROUTE_PRODUCT_PORTAL,
        method="quoteSuccess",
        snippet="this.update(routeProduct);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_railway",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="saveRouteRailway",
        snippet="routeRailwayAdminService.saveOrUpdate(routeRailway);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_railway_station",
        kind="save_or_update",
        file=_LINE_RAILWAY_STATION_ADMIN,
        method="saveData",
        snippet="saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge",
        kind="save_or_update",
        file=_LINE_CARGO_CHARGE_ADMIN_CTRL,
        method="save",
        snippet="routeCargoChargeAdminService.saveOrUpdate(routeCargoCharge);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_cargo_charge_range",
        kind="save_or_update",
        file=_LINE_CARGO_CHARGE_RANGE_ADMIN_CTRL,
        method="save",
        snippet="routeCargoChargeRangeAdminService.saveOrUpdate(routeCargoChargeRange);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_inquiry_quote",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="saveAndModify",
        snippet="routeInquiryQuoteDao.saveOrUpdate(routeInquiryQuote);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_inquiry_quote",
        kind="save_or_update",
        file=_LINE_ROUTE_PORTAL,
        method="saveAndModify",
        snippet="routeInquiryQuoteDao.saveOrUpdate(routeInquiryQuote);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_snapshot_quote",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="updateQuote",
        snippet="routeSnapshotQuoteAdminService.saveOrUpdate(routeSnapshotQuote);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_snapshot_quote",
        kind="batch_update",
        file=_LINE_ROUTE_PORTAL,
        method="updateQuote",
        snippet="routeSnapshotQuotePortalService.batchUpdate(routeSnapshotQuotes);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_inquiry",
        kind="save_or_update",
        file=_LINE_ROUTE_INQUIRY_ADMIN,
        method="save",
        snippet="dao.saveOrUpdate(targetRouteInquiry);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_inquiry",
        kind="batch_update",
        file=_LINE_ROUTE_INQUIRY_ADMIN,
        method="terminateInquiry",
        snippet="int i = dao.batchUpdate(routeInquiries);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_inquiry",
        kind="batch_update",
        file=_LINE_ROUTE_INQUIRY_ADMIN,
        method="updateStatus",
        snippet="dao.batchUpdate(awaitRouteInquiries);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_inquiry_quote_plan",
        kind="save_or_update",
        file=_LINE_QUOTE_PLAN_ADMIN,
        method="updatePlanStatus",
        snippet="dao.saveOrUpdate(plan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_inquiry_quote_plan",
        kind="save_or_update",
        file=_LINE_QUOTE_PLAN_PORTAL,
        method="updatePlanStatus",
        snippet="dao.saveOrUpdate(plan); // saveOrUpdate 会处理更新逻辑",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_inquiry_quote_plan",
        kind="save_or_update",
        file=_LINE_QUOTE_PLAN_PORTAL,
        method="updateRouteForPortal",
        snippet="dao.saveOrUpdate(quotePlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_route_inquiry_quote_plan",
        kind="save_or_update",
        file=_LINE_QUOTE_PLAN_PORTAL,
        method="saveRouteForPortal",
        snippet="dao.saveOrUpdate(quotePlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_station",
        kind="save_or_update",
        file=_LINE_STATION_ADMIN,
        method="saveData",
        snippet="this.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_station",
        kind="batch_update",
        file=_LINE_STATION_ADMIN,
        method="saveOrUpdateImportItem",
        snippet="updateNum = dao.batchUpdate(toUpdateItems);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_station",
        kind="update",
        file=_LINE_STATION_ADMIN,
        method="updateByUpdateItem",
        snippet="return dao.updateByIds(siteFeeConfigAdminItem, stationFeeConfigUpdateAdminItem.getIds());",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_station",
        kind="update",
        file=_LINE_STATION_ADMIN,
        method="updateStatusByUpdateItem",
        snippet="return dao.updateByIds(siteFeeStatusItem,stationStatusUpdateAdminItem.getIds());",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_station",
        kind="save_or_update",
        file=_LINE_STATION_BASIC,
        method="saveData",
        snippet="this.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_approval_user",
        kind="save_or_update",
        file=_LINE_ROUTE_ADMIN,
        method="recordAuditRecord",
        snippet="approvalUserAdminService.saveOrUpdate(approvalUserAdminItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_approval_user",
        kind="save_or_update",
        file=_LINE_ROUTE_PRODUCT_ADMIN,
        method="recordAuditRecord",
        snippet="approvalUserAdminService.saveOrUpdate(approvalUserAdminItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_approval_user",
        kind="save_or_update",
        file=_LINE_APPROVAL_USER_ADMIN,
        method="audit",
        snippet="dao.saveOrUpdate(approvalUser);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_approval_user",
        kind="save_or_update",
        file=_LINE_APPROVAL_USER_CTRL,
        method="save",
        snippet="approvalUserAdminService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_line_approval_history",
        kind="save_or_update",
        file=_LINE_APPROVAL_HISTORY_CTRL,
        method="save",
        snippet="approvalHistoryAdminService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted",
        kind="update",
        file=_OP_ENTRUSTED_ADMIN,
        method="quoteAdmin",
        snippet="return dao.update(entrusted);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted",
        kind="update",
        file=_OP_ENTRUSTED_ADMIN,
        method="againQuote",
        snippet="dao.update(entrusted);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted",
        kind="save_or_update",
        file=_OP_ENTRUSTED_ADMIN,
        method="saveOrUpdateEntrusted",
        snippet="dao.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted",
        kind="save_or_update",
        file=_OP_ENTRUSTED_PORTAL,
        method="updateEntrustedPortal",
        snippet="dao.saveOrUpdate(portalItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted",
        kind="update",
        file=_OP_ENTRUSTED_ADMIN,
        method="processContractAssociation",
        snippet="dao.update(entrusted);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted",
        kind="update",
        file=_OP_ENTRUSTED_ADMIN,
        method="notQuoted",
        snippet="dao.updateByCondition(entrustedStatusItem, rule);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted",
        kind="update",
        file=_OP_ENTRUSTED_ADMIN,
        method="accept",
        snippet="dao.updateByCondition(item, conditionRule);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted",
        kind="update",
        file=_OP_ENTRUSTED_ADMIN,
        method="reject",
        snippet="dao.updateByCondition(entrustedStatusItem, conditionRule);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted",
        kind="update",
        file=_OP_ENTRUSTED_ADMIN,
        method="updateEntrustedStatus",
        snippet="dao.updateByCondition(baseStatusItem, rule);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted",
        kind="update",
        file=_OP_ENTRUSTED_ADMIN,
        method="cancelOrAudit",
        snippet="dao.updateByCondition(entrustedStatusItem, conditionRule);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted",
        kind="update",
        file=_OP_ENTRUSTED_PORTAL,
        method="processAudit",
        snippet="dao.updateByCondition(statusItem, entrustedConditionRule);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted_quote",
        kind="save_or_update",
        file=_OP_QUOTE_ADMIN,
        method="save",
        snippet="return dao.saveOrUpdate(entrustedQuoteAdminItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted_quote",
        kind="update",
        file=_OP_ENTRUSTED_ADMIN,
        method="accept",
        snippet="entrustedQuoteAdminService.updateByCondition(entrustedQuoteStatusAdminItem, rule);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted_quote",
        kind="update",
        file=_OP_ENTRUSTED_ADMIN,
        method="reject",
        snippet="entrustedQuoteAdminService.updateByCondition(entrustedQuoteStatusItem, rule);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted_quote",
        kind="update",
        file=_OP_ENTRUSTED_ADMIN,
        method="cancelOrAudit",
        snippet="entrustedQuoteAdminService.updateByCondition(entrustedQuoteStatusItem, rule);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted_quote",
        kind="update",
        file=_OP_ENTRUSTED_PORTAL,
        method="processAudit",
        snippet="entrustedQuotePortalService.updateByCondition(quoteRemarkItem, quoteConditionRule);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted_order",
        kind="save_or_update",
        file=_OP_ORDER_BASIC,
        method="save",
        snippet="dao.saveOrUpdate(entrustedOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted_order",
        kind="batch_update",
        file=_OP_ORDER_ADMIN,
        method="acceptByIds",
        snippet="dao.batchUpdate(entrustedOrderList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted_order",
        kind="batch_update",
        file=_OP_ORDER_ADMIN,
        method="rejectedByIds",
        snippet="dao.batchUpdate(entrustedOrderList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_entrusted_order",
        kind="save_or_update",
        file=_OP_ORDER_ADMIN,
        method="applicationFeeStatusChange",
        snippet="dao.saveOrUpdate(entrustedOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_appointment",
        kind="save_or_update",
        file=_OP_APPOINTMENT_BASIC,
        method="save",
        snippet="dao.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_appointment",
        kind="batch_update",
        file=_OP_APPOINTMENT_ADMIN,
        method="acceptByIds",
        snippet="dao.batchUpdate(appointmentList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_appointment",
        kind="batch_update",
        file=_OP_APPOINTMENT_ADMIN,
        method="rejectedByIds",
        snippet="dao.batchUpdate(appointmentList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_appointment_vehicle",
        kind="save_or_update",
        file=_OP_VEHICLE,
        method="save",
        snippet="dao.saveOrUpdate(appointmentVehicle);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_pick_up_appointment",
        kind="save_or_update",
        file=_OP_PICKUP,
        method="save",
        snippet="dao.saveOrUpdate(pickUpAppointment);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_container",
        kind="save_or_update",
        file=_OP_CONTAINER_BASIC,
        method="save",
        snippet="dao.saveOrUpdate(container);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_general_cargo",
        kind="save_or_update",
        file=_OP_GENERAL_CARGO_BASIC,
        method="save",
        snippet="dao.saveOrUpdate(generalCargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_operation_work_node",
        kind="save_or_update",
        file=_OP_WORKNODE_BASIC,
        method="save",
        snippet="dao.saveOrUpdate(workNode);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted",
        kind="update",
        file=_ORDER_ENTRUSTED_ADMIN,
        method="saveOrUpdateEntrusted",
        snippet="dao.update(converted);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted",
        kind="update",
        file=_ORDER_ENTRUSTED_PORTAL,
        method="saveOrUpdateEntrusted",
        snippet="dao.update(entrusted);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted",
        kind="update",
        file=_ORDER_ENTRUSTED_ADMIN,
        method="generatePlanFromContract",
        snippet="dao.update(lockedEntrusted);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted",
        kind="update",
        file=_ORDER_QUOTE_ADMIN,
        method="saveQuote",
        snippet="entrustedAdminService.update(entrusted);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted_order",
        kind="save_or_update",
        file=_ENTRUSTED_ORDER_ADMIN,
        method="save",
        snippet="dao.saveOrUpdate(entrustedOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted_order",
        kind="batch_update",
        file=_ENTRUSTED_ORDER_ADMIN,
        method="saveAllData",
        snippet="dao.batchUpdate(entrustedOrders);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted_order",
        kind="update",
        file=_ORDER_ORDER_PORTAL,
        method="entrustedOrderSign",
        snippet="dao.update(order);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted_order",
        kind="batch_update",
        file=_ORDER_ORDER_PORTAL,
        method="updateBookingStatus",
        snippet="dao.batchUpdate(entrustedOrderList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_work_plan",
        kind="update",
        file=_ORDER_WORK_PLAN_ADMIN,
        method="save",
        snippet="dao.update(workPlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_work_plan",
        kind="update",
        file=_ORDER_WORK_PLAN_ADMIN,
        method="handleWorkRejection",
        snippet="dao.update(subPlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_work_plan",
        kind="update",
        file=_ORDER_WORK_PLAN_ADMIN,
        method="approveLocked",
        snippet="dao.update(masterPlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_work_plan",
        kind="update",
        file=_ORDER_WORK_PLAN_PORTAL,
        method="cancel",
        snippet="dao.update(masterPlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_work_plan",
        kind="save_or_update",
        file=_ORDER_WORK_PLAN_PORTAL,
        method="workDistribute",
        snippet="dao.saveOrUpdate(subPlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted_quote",
        kind="save_or_update",
        file=_ORDER_QUOTE_ADMIN,
        method="saveQuote",
        snippet="dao.saveOrUpdate(quote);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted_quote",
        kind="save_or_update",
        file=_ORDER_QUOTE_ADMIN,
        method="editQuote",
        snippet="dao.saveOrUpdate(quote);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted_quote",
        kind="batch_update",
        file=_ORDER_QUOTE_ADMIN,
        method="changeQuoteStatus",
        snippet="dao.batchUpdate(entrustedQuoteList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted_quote",
        kind="update",
        file=_ORDER_QUOTE_PORTAL,
        method="shipperReject",
        snippet="dao.update(entrustedQuote);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted_quote",
        kind="update",
        file=_ORDER_QUOTE_PORTAL,
        method="shipperApprove",
        snippet="dao.update(entrustedQuote);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted_cargo",
        kind="save_or_update",
        file=_ORDER_ENTRUSTED_ADMIN,
        method="saveOrUpdateEntrusted",
        snippet="entrustedCargoService.saveOrUpdate(cargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted_cargo",
        kind="save_or_update",
        file=_ENTRUSTED_ORDER_ADMIN,
        method="save",
        snippet="entrustedCargoAdminService.saveOrUpdate(entrustedCargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_entrusted_order_settlement",
        kind="save_or_update",
        file=_ENTRUSTED_ORDER_ADMIN,
        method="save",
        snippet="entrustedOrderSettlementAdminService.saveOrUpdate(orderSettlement);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_container",
        kind="save_or_update",
        file=_ENTRUSTED_ORDER_ADMIN,
        method="saveContainerItems",
        snippet="containerAdminService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_node",
        kind="save_or_update",
        file=_ENTRUSTED_ORDER_ADMIN,
        method="saveOrderNode",
        snippet="orderNodeAdminService.saveOrUpdate(orderNode);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_booking_application",
        kind="save_or_update",
        file=_ORDER_BOOKING_ADMIN,
        method="save",
        snippet="dao.saveOrUpdate(bookingApplicationAdminItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_booking_application",
        kind="save_or_update",
        file=_ORDER_BOOKING_BASIC,
        method="updateStatus",
        snippet="dao.saveOrUpdate(bookingApplication);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_booking_application_confirm",
        kind="save_or_update",
        file=_ORDER_CONFIRM_ADMIN,
        method="saveOrUpdateInfo",
        snippet="this.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_attachment",
        kind="save_or_update",
        file=_ORDER_ATTACH_BASIC,
        method="uploadAndSave",
        snippet="saveOrUpdate(attachment);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_file",
        kind="save_or_update",
        file=_ORDER_FILE,
        method="upload",
        snippet="dao.saveOrUpdate(entrustedOrderFile);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_outbound_order",
        kind="save_or_update",
        file=_ORDER_WMS,
        method="process",
        snippet="outboundOrderDao.saveOrUpdate(outboundOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_outbound_order",
        kind="update",
        file=_ORDER_TRANSPORT,
        method="refreshOrderStatus",
        snippet="outboundOrderDao.update(outboundOrder);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_outbound_order_detail",
        kind="save_or_update",
        file=_ORDER_WMS,
        method="syncDetails",
        snippet="outboundOrderDetailDao.saveOrUpdate(detail);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_outbound_entrusted_relation",
        kind="save_or_update",
        file=_ORDER_WMS,
        method="saveEntrustedRelation",
        snippet="outboundOrderEntrustedRelationDao.saveOrUpdate(relation);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_order_outbound_transport_relation",
        kind="save_or_update",
        file=_ORDER_TRANSPORT,
        method="bindLoadedTransport",
        snippet="outboundTransportRelationDao.saveOrUpdate(relation);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_route",
        kind="save_or_update",
        file=_BT_ROUTE,
        method="saveBtRoute",
        snippet="saveOrUpdate(btRoute);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_daily_plan",
        kind="save_or_update",
        file=_BT_DAILY,
        method="cancel",
        snippet="saveOrUpdate(plan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_daily_plan",
        kind="save_or_update",
        file=_BT_DAILY,
        method="confirmBooking",
        snippet="saveOrUpdate(plan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_daily_plan",
        kind="save_or_update",
        file=_BT_DAILY,
        method="updateDailyPlanDispatch",
        snippet="saveOrUpdate(plan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_daily_plan",
        kind="save_or_update",
        file=_BT_DAILY,
        method="complete",
        snippet="saveOrUpdate(plan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_DEPARTURE,
        method="saveBtDeparturePlan",
        snippet="saveOrUpdate(departurePlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_DEPARTURE,
        method="publish",
        snippet="saveOrUpdate(departurePlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_DEPARTURE,
        method="cancel",
        snippet="saveOrUpdate(departurePlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_DEPARTURE,
        method="execute",
        snippet="saveOrUpdate(departurePlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_DEPARTURE,
        method="complete",
        snippet="saveOrUpdate(departurePlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_TRAIN_PLAN,
        method="saveBtTrainPlanList",
        snippet="saveOrUpdate(plan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_TRAIN_PLAN,
        method="execute",
        snippet="saveOrUpdate(plan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_TRAIN_PLAN,
        method="complete",
        snippet="saveOrUpdate(plan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_DAILY,
        method="executeDeparturePlanByDailyDispatch",
        snippet="departurePlanDao.saveOrUpdate(departurePlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_DEPARTURE_CHANGE,
        method="saveChangeRecord",
        snippet="departurePlanDao.saveOrUpdate(departurePlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_MONITOR,
        method="handleException",
        snippet="departurePlanDao.saveOrUpdate(departurePlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan_station",
        kind="save_or_update",
        file=_BT_DEPARTURE_STATION,
        method="saveBtDeparturePlanStation",
        snippet="saveOrUpdate(station);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan_station",
        kind="save_or_update",
        file=_BT_DEPARTURE_STATION,
        method="saveActualTimeList",
        snippet="saveOrUpdate(station);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan_station",
        kind="save_or_update",
        file=_BT_MONITOR,
        method="handleException",
        snippet="stationDao.saveOrUpdate(station);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan_daily_plan",
        kind="save_or_update",
        file=_BT_DEPARTURE_DAILY,
        method="remove",
        snippet="saveOrUpdate(relation);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan_daily_plan",
        kind="save_or_update",
        file=_BT_DEPARTURE_DAILY,
        method="saveRelation",
        snippet="saveOrUpdate(relation);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan_change_record",
        kind="save_or_update",
        file=_BT_DEPARTURE_CHANGE,
        method="saveChangeRecord",
        snippet="saveOrUpdate(record);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_monthly_entrusted",
        kind="save_or_update",
        file=_BT_MONTHLY,
        method="save",
        snippet="saveOrUpdate(monthlyEntrusted);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_monthly_entrusted",
        kind="save_or_update",
        file=_BT_MONTHLY,
        method="createReportPlan",
        snippet="saveOrUpdate(monthlyEntrusted);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_monthly_entrusted",
        kind="save_or_update",
        file=_BT_SUPPLEMENT,
        method="updateMonthlyDemandSupplement",
        snippet="monthlyEntrustedDao.saveOrUpdate(monthlyEntrusted);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_monthly_entrusted",
        kind="save_or_update",
        file=_BT_SUPPLEMENT,
        method="markMonthlyDemandSupplement",
        snippet="monthlyEntrustedDao.saveOrUpdate(monthlyEntrusted);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_monthly_entrusted_supplement",
        kind="save_or_update",
        file=_BT_SUPPLEMENT,
        method="save",
        snippet="saveOrUpdate(supplement);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_monthly_entrusted_supplement",
        kind="save_or_update",
        file=_BT_SUPPLEMENT,
        method="confirm",
        snippet="saveOrUpdate(supplement);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_monthly_entrusted_supplement",
        kind="save_or_update",
        file=_BT_SUPPLEMENT,
        method="reject",
        snippet="saveOrUpdate(supplement);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_waybill",
        kind="save_or_update",
        file=_BT_WAYBILL,
        method="arriveWaybill",
        snippet="saveOrUpdate(waybill);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_train_operation_tracking",
        kind="save_or_update",
        file=_BT_TRACKING,
        method="saveBtTrainOperationTracking",
        snippet="saveOrUpdate(operation);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_train_operation_tracking",
        kind="save_or_update",
        file=_BT_TRACKING,
        method="start",
        snippet="saveOrUpdate(operation);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_train_operation_tracking",
        kind="save_or_update",
        file=_BT_TRACKING,
        method="complete",
        snippet="saveOrUpdate(operation);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_train_operation_tracking",
        kind="save_or_update",
        file=_BT_TRACKING,
        method="recover",
        snippet="saveOrUpdate(operation);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_train_operation_tracking",
        kind="save_or_update",
        file=_BT_EXCEPTION,
        method="syncOperationExceptionState",
        snippet="operationDao.saveOrUpdate(operation);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_train_operation_tracking",
        kind="save_or_update",
        file=_BT_MONITOR,
        method="handleException",
        snippet="operationDao.saveOrUpdate(operation);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_train_operation_exception_record",
        kind="save_or_update",
        file=_BT_EXCEPTION,
        method="saveRecord",
        snippet="saveOrUpdate(record);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_expense",
        kind="save_or_update",
        file=_SETTLE_EXPENSE,
        method="save",
        snippet="saveOrUpdate(expense);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_expense",
        kind="batch_update",
        file=_SETTLE_INVOICE,
        method="save",
        snippet="expenseDao.batchUpdate(expenses);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_bt_expense",
        kind="save_or_update",
        file=_SETTLE_BT_EXPENSE,
        method="save",
        snippet="saveOrUpdate(expense);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_payable_bill",
        kind="save_or_update",
        file=_SETTLE_PAYABLE,
        method="save",
        snippet="saveOrUpdate(payableBill);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_payable_bill",
        kind="batch_update",
        file=_SETTLE_PAYABLE_ADMIN,
        method="batchSubmitPayment",
        snippet="return batchUpdate(payableBillList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_receivable_bill",
        kind="save_or_update",
        file=_SETTLE_RECEIVABLE,
        method="save",
        snippet="saveOrUpdate(receivableBill);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_payment_apply",
        kind="update",
        file=_SETTLE_APPLY,
        method="approve",
        snippet="update(paymentApply);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_sales_invoice",
        kind="save_or_update",
        file=_SETTLE_INVOICE,
        method="save",
        snippet="saveOrUpdate(salesInvoice);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_prepayment",
        kind="save_or_update",
        file=_SETTLE_PREPAY,
        method="save",
        snippet="saveOrUpdate(prepayment);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_prepayment",
        kind="batch_update",
        file=_SETTLE_PREPAY,
        method="batchPaymentApply",
        snippet="return batchUpdate(prepaymentList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_owner_fund",
        kind="save_or_update",
        file=_SETTLE_FUND,
        method="save",
        snippet="saveOrUpdate(ownerFund);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_operation_fee",
        kind="save_or_update",
        file=_SETTLE_OP_FEE,
        method="saveOrUpdateReturnEntity",
        snippet="saveOrUpdate(operationFee);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_operation_fee_detail",
        kind="save_or_update",
        file=_SETTLE_OP_FEE,
        method="generateBillingOrder",
        snippet="dao.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_payment_confirmation",
        kind="save_or_update",
        file=_SETTLE_PAY_CONFIRM,
        method="save",
        snippet="saveOrUpdate(paymentConfirmation);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_receipt_confirmation",
        kind="save_or_update",
        file=_SETTLE_RCV_CONFIRM,
        method="save",
        snippet="saveOrUpdate(receiptConfirmation);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_collection",
        kind="save_or_update",
        file=_SETTLE_COLLECTION,
        method="save",
        snippet="saveOrUpdate(precollection);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_settlement_advance_payment",
        kind="save_or_update",
        file=_SETTLE_ADVANCE,
        method="save",
        snippet="saveOrUpdate(advancePayment);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_daily_plan",
        kind="save_or_update",
        file=_BT_DAILY,
        method="dispatchByDeparturePlan",
        snippet="saveOrUpdate(plan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_bt_departure_plan",
        kind="save_or_update",
        file=_BT_DEPARTURE,
        method="change",
        snippet="saveOrUpdate(departurePlan);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order",
        kind="update",
        file=_DECL_ORDER,
        method="updateGoodsDeclarationStatus",
        snippet="dao.update(first);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_transport",
        kind="save_or_update",
        file=_DECL_TRANSPORT,
        method="save",
        snippet="saveOrUpdate(dbOrderTransport);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_declare",
        kind="save_or_update",
        file=_DECL_DECLARE,
        method="save",
        snippet="saveOrUpdate(dbOrderDeclare);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine",
        kind="save_or_update",
        file=_DECL_QUARANTINE,
        method="save",
        snippet="saveOrUpdate(orderQuarantine);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_cargo",
        kind="save_or_update",
        file=_DECL_CARGO,
        method="batchSave",
        snippet="saveOrUpdate(orderCargo);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_commodity",
        kind="batch_update",
        file=_DECL_COMMODITY,
        method="updateStatus",
        snippet="dao.batchUpdate(commodityList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_basic_information",
        kind="batch_update",
        file=_DECL_BASIC_INFO,
        method="updateStatus",
        snippet="dao.batchUpdate(basicInformationList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_commodity_basic_data",
        kind="batch_update",
        file=_DECL_BASIC_DATA,
        method="updateStatus",
        snippet="dao.batchUpdate(commodityBasicDataList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_origin",
        kind="batch_update",
        file=_DECL_ORIGIN,
        method="updateStatus",
        snippet="dao.batchUpdate(originList);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order",
        kind="save_or_update",
        file=_DECL_ORDER,
        method="save",
        snippet="saveOrUpdate(order);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order",
        kind="update",
        file=_DECL_ORDER,
        method="updateOrderStatusByReceipt",
        snippet="dao.update(order);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order",
        kind="save_or_update",
        file=_DECL_ORDER_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order",
        kind="save_or_update",
        file=_DECL_ORDER_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_transport",
        kind="save_or_update",
        file=_DECL_TRANSPORT_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderTransportItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_transport",
        kind="save_or_update",
        file=_DECL_TRANSPORT_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderTransportItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_declare",
        kind="save_or_update",
        file=_DECL_DECLARE_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderDeclareItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_declare",
        kind="save_or_update",
        file=_DECL_DECLARE_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderDeclareItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine",
        kind="save_or_update",
        file=_DECL_QUARANTINE_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderQuarantineItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine",
        kind="save_or_update",
        file=_DECL_QUARANTINE_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderQuarantineItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine_enterprise",
        kind="save_or_update",
        file=_DECL_ENTERPRISE,
        method="batchSave",
        snippet="saveOrUpdate(quarantineEnterprise);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine_enterprise",
        kind="save_or_update",
        file=_DECL_ENTERPRISE_ADMIN,
        method="save",
        snippet="saveOrUpdate(quarantineEnterpriseItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_quarantine_enterprise",
        kind="save_or_update",
        file=_DECL_ENTERPRISE_PORTAL,
        method="save",
        snippet="saveOrUpdate(quarantineEnterpriseItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_cargo",
        kind="save_or_update",
        file=_DECL_CARGO_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderCargoItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_cargo",
        kind="save_or_update",
        file=_DECL_CARGO_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderCargoItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_cargo_attribute",
        kind="save_or_update",
        file=_DECL_CARGO,
        method="batchSave",
        snippet="orderCargoAttributeBasicService.saveOrUpdate(orderCargoAttribute);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_cargo_attribute",
        kind="save_or_update",
        file=_DECL_ATTRIBUTE,
        method="batchSave",
        snippet="saveOrUpdate(orderCargoAttribute);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_cargo_attribute",
        kind="save_or_update",
        file=_DECL_ATTRIBUTE_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderCargoAttributeItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_cargo_attribute",
        kind="save_or_update",
        file=_DECL_ATTRIBUTE_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderCargoAttributeItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_container",
        kind="save_or_update",
        file=_DECL_CONTAINER,
        method="batchSave",
        snippet="saveOrUpdate(container);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_container",
        kind="save_or_update",
        file=_DECL_CONTAINER_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderContainerItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_container",
        kind="save_or_update",
        file=_DECL_CONTAINER_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderContainerItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_document",
        kind="save_or_update",
        file=_DECL_DOCUMENT,
        method="batchSave",
        snippet="saveOrUpdate(orderDocument);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_document",
        kind="save_or_update",
        file=_DECL_DOCUMENT_ADMIN,
        method="save",
        snippet="saveOrUpdate(orderDocumentItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_order_document",
        kind="save_or_update",
        file=_DECL_DOCUMENT_PORTAL,
        method="save",
        snippet="saveOrUpdate(orderDocumentItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_entrust",
        kind="save_or_update",
        file=_DECL_ENTRUST,
        method="save",
        snippet="return saveOrUpdate(entrust);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_entrust",
        kind="update",
        file=_DECL_ENTRUST_ADMIN,
        method="approveEntrust",
        snippet="update(entrust);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_entrust",
        kind="update",
        file=_DECL_ENTRUST_ADMIN,
        method="rejectEntrust",
        snippet="update(entrust);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_attachment",
        kind="save_or_update",
        file=_DECL_ATTACH,
        method="save",
        snippet="saveOrUpdate(attachmentItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_attachment",
        kind="save_or_update",
        file=_DECL_ATTACH_PORTAL,
        method="save",
        snippet="saveOrUpdate(attachmentItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_commodity",
        kind="save_or_update",
        file=_DECL_COMMODITY,
        method="save",
        snippet="saveOrUpdate(commodityItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_commodity",
        kind="save_or_update",
        file=_DECL_COMMODITY_PORTAL,
        method="save",
        snippet="saveOrUpdate(commodityItem);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_commodity",
        kind="batch_update",
        file=_DECL_COMMODITY,
        method="saveOrUpdateImportItem",
        snippet="updateNum = dao.batchUpdate(toUpdateItems);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_commodity_catalog",
        kind="save_or_update",
        file=_DECL_CATALOG,
        method="saveOrUpdate",
        snippet="boolean b = dao.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_basic_information",
        kind="save_or_update",
        file=_DECL_BASIC_INFO,
        method="saveOrUpdate",
        snippet="dao.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_basic_information",
        kind="batch_update",
        file=_DECL_BASIC_INFO,
        method="saveOrUpdateImportItem",
        snippet="updateNum = dao.batchUpdate(toUpdateItems);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_commodity_basic_data",
        kind="save_or_update",
        file=_DECL_BASIC_DATA,
        method="saveOrUpdate",
        snippet="dao.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_commodity_basic_data",
        kind="batch_update",
        file=_DECL_BASIC_DATA,
        method="validateAndSaveImportCommodityBasicData",
        snippet="updateNum = dao.batchUpdate(toUpdateItems);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_origin",
        kind="save_or_update",
        file=_DECL_ORIGIN,
        method="saveOrUpdate",
        snippet="dao.saveOrUpdate( item);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_origin",
        kind="batch_update",
        file=_DECL_ORIGIN,
        method="saveOrUpdateImportItem",
        snippet="updateNum = dao.batchUpdate(toUpdateItems);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_interface_file_transfer_record",
        kind="update",
        file=_DECL_FILE_RESPONSE,
        method="updateFileTransferRecord",
        snippet="fileTransferRecordBasicService.update(fileTransferRecord);",
    ),
    SeedUpdate(
        table=f"{MTP}.cs_dsly_declaration_interface_file_transfer_record",
        kind="update",
        file=_DECL_FILE_RESPONSE,
        method="updateFileTransferRecordReceipt",
        snippet="fileTransferRecordBasicService.update(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="update",
        file=_MEMBER_USER_PORTAL,
        method="updateLocalMobile",
        snippet="dao.update(userInfo);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="save_or_update",
        file=_MEMBER_USER,
        method="saveOrUpdate",
        snippet="saveOrUpdate(userInfo);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="save_or_update",
        file=_MEMBER_USER,
        method="saveOrUpdateCustomsDeclarant",
        snippet="saveOrUpdate(declarantUserInfo);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="batch_update",
        file=_MEMBER_USER,
        method="enable",
        snippet="dao.batchUpdate(userInfoList);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="batch_update",
        file=_MEMBER_USER,
        method="disable",
        snippet="dao.batchUpdate(userInfoList);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="save_or_update",
        file=_MEMBER_USER_PORTAL,
        method="saveOrUpdateEnterpriseUserInfo",
        snippet="saveOrUpdate(userInfo);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_info",
        kind="update",
        file=_MEMBER_USER_PORTAL,
        method="updateUserInfo",
        snippet="dao.update(userInfo);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="batch_update",
        file=_MEMBER_USER,
        method="bindAuthDetailIds",
        snippet="userAuthInfoService.batchUpdate(toUpdate);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="update",
        file=_MEMBER_USER,
        method="saveOrUpdateCustomsDeclarant",
        snippet="userAuthInfoService.update(userAuthInfo);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="batch_update",
        file=_MEMBER_USER_AUTH_ADMIN,
        method="syncBidderAuthStatusByCompanyUsci",
        snippet="dao.batchUpdate(bidderAuthInfos);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="update",
        file=_MEMBER_USER_PORTAL,
        method="processBidderAuth",
        snippet="userAuthInfoPortalService.update(bidderAuthInfo);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="update",
        file=_MEMBER_USER_PORTAL,
        method="processShipperAuth",
        snippet="userAuthInfoPortalService.update(shipperAuthInfo);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="batch_update",
        file=_MEMBER_USER_PORTAL,
        method="processCarrierAuth",
        snippet="userAuthInfoPortalService.batchUpdate(toUpdate);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="batch_update",
        file=_MEMBER_USER_PORTAL,
        method="processPersonalAuth",
        snippet="userAuthInfoPortalService.batchUpdate(toUpdate);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="batch_update",
        file=_MEMBER_USER_PORTAL,
        method="persistAuthInfoChanges",
        snippet="userAuthInfoPortalService.batchUpdate(toUpdate);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="batch_update",
        file=_MEMBER_USER_PORTAL,
        method="bindAuthDetailIds",
        snippet="userAuthInfoPortalService.batchUpdate(toUpdate);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_auth_info",
        kind="update",
        file=_MEMBER_RISK,
        method="rejectCertifyingShipperAuth",
        snippet="userAuthInfoPortalService.update(userAuthInfo);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_user_identity_auth_detail",
        kind="batch_update",
        file=_MEMBER_AUTH_DETAIL,
        method="saveOrUpdateBySnapshot",
        snippet="batchUpdate(toUpdate);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_contract",
        kind="save_or_update",
        file=_MEMBER_CONTRACT,
        method="syncContractInfo",
        snippet="dao.saveOrUpdate(contract);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_contract",
        kind="save_or_update",
        file=_MEMBER_CONTRACT,
        method="save",
        snippet="saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_contract",
        kind="batch_update",
        file=_MEMBER_CONTRACT,
        method="changeEnable",
        snippet="batchUpdate(contractList);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_contract",
        kind="batch_update",
        file=_MEMBER_CONTRACT,
        method="changeDisable",
        snippet="batchUpdate(contractExtendList);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_contract_operation",
        kind="save_or_update",
        file=_MEMBER_CONTRACT_OP,
        method="save",
        snippet="saveOrUpdate(contractOperationAdminItem);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_shipper_level",
        kind="save_or_update",
        file=_MEMBER_LEVEL,
        method="save",
        snippet="dao.saveOrUpdate(shipperLevelItem);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_shipper_level",
        kind="save_or_update",
        file=_MEMBER_LEVEL,
        method="updateLevelStatus",
        snippet="dao.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_shipper_level_history",
        kind="save_or_update",
        file=_MEMBER_LEVEL_HISTORY_CTRL,
        method="save",
        snippet="shipperLevelHistoryService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_attachment",
        kind="save_or_update",
        file=_MEMBER_LEVEL,
        method="save",
        snippet="attachmentDao.saveOrUpdate(attachmentAdminItem);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_invoice",
        kind="save_or_update",
        file=_MEMBER_INVOICE,
        method="saveOrEdit",
        snippet="return dao.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_message_recipient",
        kind="save_or_update",
        file=_MEMBER_MSG,
        method="saveOrUpdateMessageRecipient",
        snippet="dao.saveOrUpdate(recipient);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_entrusted_order_complain",
        kind="save_or_update",
        file=_MEMBER_COMPLAIN,
        method="save",
        snippet="dao.saveOrUpdate(entrustedOrderComplainPortalItem);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_entrusted_order_complain",
        kind="save_or_update",
        file=_MEMBER_COMPLAIN_ADMIN,
        method="audit",
        snippet="dao.saveOrUpdate(complain);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_member_entrusted_order_evaluation",
        kind="save_or_update",
        file=_MEMBER_EVAL_CTRL,
        method="save",
        snippet="entrustedOrderEvaluationPortalService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_kpi",
        kind="save_or_update",
        file=_COCKPIT_KPI_CTRL,
        method="save",
        snippet="cockpitKpiService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_cargo_summary",
        kind="save_or_update",
        file=_COCKPIT_SUMMARY_CTRL,
        method="save",
        snippet="cockpitCargoSummaryService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_cargo_category",
        kind="save_or_update",
        file=_COCKPIT_CATEGORY_CTRL,
        method="save",
        snippet="cockpitCargoCategoryService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_enterprise_rank",
        kind="save_or_update",
        file=_COCKPIT_ENTERPRISE_CTRL,
        method="save",
        snippet="cockpitEnterpriseRankService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_city_flow",
        kind="save_or_update",
        file=_COCKPIT_CITY_FLOW_CTRL,
        method="save",
        snippet="cockpitCityFlowService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_city_flow_cargo",
        kind="save_or_update",
        file=_COCKPIT_CITY_CARGO_CTRL,
        method="save",
        snippet="cockpitCityFlowCargoService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_map_flow",
        kind="save_or_update",
        file=_COCKPIT_MAP_CTRL,
        method="save",
        snippet="cockpitMapFlowService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_map_flow",
        kind="save_or_update",
        file=_COCKPIT_DATA,
        method="saveMapFlow",
        snippet="mapFlowService.saveOrUpdate(entity);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_timeliness_route",
        kind="save_or_update",
        file=_COCKPIT_TIMELINESS_CTRL,
        method="save",
        snippet="cockpitTimelinessRouteService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_station_turnover",
        kind="save_or_update",
        file=_COCKPIT_STATION_CTRL,
        method="save",
        snippet="cockpitStationTurnoverService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_ontime_summary",
        kind="save_or_update",
        file=_COCKPIT_ONTIME_SUMMARY_CTRL,
        method="save",
        snippet="cockpitOntimeSummaryService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_ontime_route",
        kind="save_or_update",
        file=_COCKPIT_ONTIME_ROUTE_CTRL,
        method="save",
        snippet="cockpitOntimeRouteService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_congestion",
        kind="save_or_update",
        file=_COCKPIT_CONGESTION_CTRL,
        method="save",
        snippet="cockpitCongestionService.saveOrUpdate(item);",
    ),
    SeedUpdate(
        table=f"{PORTAL}.cs_portal_cockpit_accident",
        kind="save_or_update",
        file=_COCKPIT_ACCIDENT_CTRL,
        method="save",
        snippet="cockpitAccidentService.saveOrUpdate(item);",
    ),
)


@dataclass(frozen=True, slots=True)
class SeedProjection:
    """The whole seeded generation, already shaped like the repository reads it."""

    generation: TableRelationGenerationRecord
    tables: tuple[TableRelationTableRecord, ...]
    edges: tuple[TableRelationEdgeRecord, ...]
    code_sites: tuple[TableRelationCodeSiteRecord, ...] = ()
    write_sites: tuple[TableRelationWriteSiteRecord, ...] = ()
    update_sites: tuple[TableRelationUpdateSiteRecord, ...] = ()


def _split_table(key: str) -> tuple[str, str, str]:
    database_key, schema_name, table_name = key.split(".")
    return database_key, schema_name, table_name


def _split_column(key: str) -> tuple[str, str, str, str]:
    database_key, schema_name, table_name, column_name = key.split(".")
    return database_key, schema_name, table_name, column_name


def _fingerprint(left: tuple[str, ...], right: tuple[str, ...]) -> str:
    return hashlib.sha256("|".join((*left, *right)).encode("utf-8")).hexdigest()


def _canonical(
    edge: SeedEdge,
) -> tuple[tuple[str, str, str, str], tuple[str, str, str, str], str]:
    """Order the two endpoints the way the table stores them.

    The check constraint compares the endpoints in the C collation, which for
    these identifiers is the same order Python's ``<`` produces.
    """
    parent = _split_column(edge.parent)
    child = _split_column(edge.child)
    if parent < child:
        return parent, child, "left_to_right"
    return child, parent, "right_to_left"


def _measurement(measured: SeedMeasurement) -> TableRelationMeasurement:
    return TableRelationMeasurement(
        child_key_kind=measured.key_kind,
        parent_key_kind=measured.key_kind,
        child_table_rows=measured.child_table_rows,
        child_rows_with_value=measured.child_rows_with_value,
        child_distinct_keys=measured.child_distinct_keys,
        parent_rows_with_value=measured.parent_rows_with_value,
        parent_distinct_keys=measured.parent_distinct_keys,
        orphan_keys=measured.orphan_keys,
    )


def _validate() -> None:
    """Fail on a declaration the storage layer would reject anyway."""
    for seed_edge in SEED_EDGES:
        for endpoint in (seed_edge.parent, seed_edge.child):
            column_name = _split_column(endpoint)[3]
            # Bookkeeping columns never take part in a relation, not even here.
            if is_common_column(column_name):
                raise ValueError(f"{endpoint} 用了公共字段 {column_name}，公共字段不参与关联")
        # The counts are transcribed by hand, so they are checked for being
        # arithmetically possible. The data verdict is not checked, because it is
        # derived from them and has nothing of its own to be wrong about.
        check_counts(_measurement(seed_edge.measured))
        db_cardinality, db_evidence = seed_edge.db_verdict
        check_verdict(
            code_cardinality=seed_edge.code_cardinality,
            code_evidence=seed_edge.code_evidence,
            db_cardinality=db_cardinality,
            db_evidence=db_evidence,
        )
        # The code verdict has to be one of its own sites' conclusions. This is
        # what caught the four ``batchInsert`` misreadings, and it is why they
        # cannot come back by transcription.
        check_sites(
            code_cardinality=seed_edge.code_cardinality,
            code_evidence=seed_edge.code_evidence,
            site_kinds=tuple(site.kind for site in seed_edge.sites),
        )
    seen_calls: set[tuple[str, str, str]] = set()
    for seed_write in SEED_WRITES:
        if seed_write.table not in SEED_TABLES:
            raise ValueError(f"插入入口指向未登记的表 {seed_write.table}")
        check_write_site(
            kind=seed_write.kind,
            file_path=seed_write.file,
            method_name=seed_write.method,
            snippet=seed_write.snippet,
        )
        call = (seed_write.table, seed_write.file, seed_write.method)
        if call in seen_calls:
            raise ValueError(f"同一张表的同一个方法不能记两次插入入口：{call}")
        seen_calls.add(call)
    seen_update_calls: set[tuple[str, str, str]] = set()
    for seed_update in SEED_UPDATES:
        if seed_update.table not in SEED_TABLES:
            raise ValueError(f"更新入口指向未登记的表 {seed_update.table}")
        check_update_site(
            kind=seed_update.kind,
            file_path=seed_update.file,
            method_name=seed_update.method,
            snippet=seed_update.snippet,
        )
        call = (seed_update.table, seed_update.file, seed_update.method)
        if call in seen_update_calls:
            raise ValueError(f"同一张表的同一个方法不能记两次更新入口：{call}")
        seen_update_calls.add(call)


def build_seed_projection(
    *,
    workspace_id: str,
    environment: str = "uat",
    generation_id: str | None = None,
    published_at: datetime | None = None,
) -> SeedProjection:
    resolved_generation_id = generation_id or uuid4().hex
    resolved_published_at = published_at or datetime.now(UTC)
    _validate()

    # The two dimensions are refreshed on their own schedules, so they carry
    # their own timestamps. Reading the code came first here, as it always will:
    # it is what decides which columns are worth probing.
    code_checked_at = resolved_published_at - timedelta(hours=2)
    db_measured_at = resolved_published_at - timedelta(minutes=20)

    edges: list[TableRelationEdgeRecord] = []
    code_sites: list[TableRelationCodeSiteRecord] = []
    for seed_edge in SEED_EDGES:
        left, right, orientation = _canonical(seed_edge)
        db_cardinality, db_evidence = seed_edge.db_verdict
        edge_id = uuid4().hex
        code_sites.extend(
            TableRelationCodeSiteRecord(
                edge_id=edge_id,
                kind=site.kind,
                file_path=site.file,
                method_name=site.method,
                snippet=site.snippet,
                position=position,
            )
            for position, site in enumerate(seed_edge.sites)
        )
        edges.append(
            TableRelationEdgeRecord(
                id=edge_id,
                generation_id=resolved_generation_id,
                left_database_key=left[0],
                left_schema=left[1],
                left_table=left[2],
                left_column=left[3],
                right_database_key=right[0],
                right_schema=right[1],
                right_table=right[2],
                right_column=right[3],
                orientation=orientation,
                code_cardinality=seed_edge.code_cardinality,
                code_evidence=seed_edge.code_evidence,
                db_cardinality=db_cardinality,
                db_evidence=db_evidence,
                measurement=_measurement(seed_edge.measured),
                code_checked_at=code_checked_at,
                db_measured_at=db_measured_at,
                cross_database=seed_edge.cross_database,
            )
        )

    # Counted through the read projection rather than off the declarations above,
    # so the table list's numbers are the list's numbers by construction.
    counters = project_table_counters(edges=edges)
    tables: list[TableRelationTableRecord] = []
    for seed_table in SEED_TABLES:
        identity = _split_table(seed_table)
        counter = counters.get(identity, TableRelationCounters())
        tables.append(
            TableRelationTableRecord(
                generation_id=resolved_generation_id,
                database_key=identity[0],
                schema_name=identity[1],
                table_name=identity[2],
                relation_count=counter.relation_count,
                hidden_count=counter.hidden_count,
            )
        )
    unknown = sorted(counters.keys() - {_split_table(table) for table in SEED_TABLES})
    if unknown:
        listed = "，".join(".".join(identity) for identity in unknown)
        raise ValueError(f"这些表有关联但没有登记在 SEED_TABLES 里：{listed}")

    positions: dict[tuple[str, str, str], int] = {}
    write_sites: list[TableRelationWriteSiteRecord] = []
    for seed_write in SEED_WRITES:
        identity = _split_table(seed_write.table)
        position = positions.get(identity, 0)
        positions[identity] = position + 1
        write_sites.append(
            TableRelationWriteSiteRecord(
                generation_id=resolved_generation_id,
                database_key=identity[0],
                schema_name=identity[1],
                table_name=identity[2],
                kind=seed_write.kind,
                file_path=seed_write.file,
                method_name=seed_write.method,
                snippet=seed_write.snippet,
                position=position,
            )
        )

    update_positions: dict[tuple[str, str, str], int] = {}
    update_sites: list[TableRelationUpdateSiteRecord] = []
    for seed_update in SEED_UPDATES:
        identity = _split_table(seed_update.table)
        position = update_positions.get(identity, 0)
        update_positions[identity] = position + 1
        update_sites.append(
            TableRelationUpdateSiteRecord(
                generation_id=resolved_generation_id,
                database_key=identity[0],
                schema_name=identity[1],
                table_name=identity[2],
                kind=seed_update.kind,
                file_path=seed_update.file,
                method_name=seed_update.method,
                snippet=seed_update.snippet,
                position=position,
            )
        )

    dead = [edge for edge in edges if is_dead_column(edge.db_evidence)]
    generation = TableRelationGenerationRecord(
        id=resolved_generation_id,
        workspace_id=workspace_id,
        environment=environment,
        status="published",
        revision=1,
        edge_count=len(edges),
        relation_count=len(edges) - len(dead),
        hidden_count=len(dead),
        published_at=resolved_published_at,
    )
    return SeedProjection(
        generation=generation,
        tables=tuple(tables),
        edges=tuple(edges),
        code_sites=tuple(code_sites),
        write_sites=tuple(write_sites),
        update_sites=tuple(update_sites),
    )


def load_into_memory(
    projection: SeedProjection,
) -> InMemoryTableRelationRepository:
    repository = InMemoryTableRelationRepository()
    repository.add_generation(
        projection.generation,
        tables=list(projection.tables),
        edges=list(projection.edges),
        code_sites=list(projection.code_sites),
        write_sites=list(projection.write_sites),
        update_sites=list(projection.update_sites),
    )
    return repository


def insert_projection(
    connection: psycopg.Connection[Any],
    projection: SeedProjection,
) -> None:
    generation = projection.generation
    connection.execute(
        """
        DELETE FROM workspace_table_relation_generations
        WHERE workspace_id = %s
        """,
        (generation.workspace_id,),
    )
    connection.execute(
        """
        INSERT INTO workspace_table_relation_generations (
            id, workspace_id, environment, status, revision,
            edge_count, relation_count, hidden_count, published_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        """,
        (
            generation.id,
            generation.workspace_id,
            generation.environment,
            generation.status,
            generation.revision,
            generation.edge_count,
            generation.relation_count,
            generation.hidden_count,
            generation.published_at,
        ),
    )
    for table in projection.tables:
        connection.execute(
            """
            INSERT INTO workspace_table_relation_tables (
                id, generation_id, database_key, schema_name, table_name,
                relation_count, hidden_count
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4().hex,
                table.generation_id,
                table.database_key,
                table.schema_name,
                table.table_name,
                table.relation_count,
                table.hidden_count,
            ),
        )
    for edge in projection.edges:
        left = (edge.left_database_key, edge.left_schema, edge.left_table, edge.left_column)
        right = (
            edge.right_database_key,
            edge.right_schema,
            edge.right_table,
            edge.right_column,
        )
        connection.execute(
            """
            INSERT INTO workspace_table_relation_edges (
                id, generation_id,
                left_database_key, left_schema, left_table, left_column,
                right_database_key, right_schema, right_table, right_column,
                pair_fingerprint, orientation,
                code_cardinality, code_evidence, db_cardinality, db_evidence,
                code_checked_at, db_measured_at,
                child_key_kind, parent_key_kind,
                child_table_rows, child_rows_with_value, child_distinct_keys,
                parent_rows_with_value, parent_distinct_keys, orphan_keys,
                cross_database
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                edge.id,
                edge.generation_id,
                *left,
                *right,
                _fingerprint(left, right),
                edge.orientation,
                edge.code_cardinality,
                edge.code_evidence,
                edge.db_cardinality,
                edge.db_evidence,
                edge.code_checked_at,
                edge.db_measured_at,
                edge.measurement.child_key_kind,
                edge.measurement.parent_key_kind,
                edge.measurement.child_table_rows,
                edge.measurement.child_rows_with_value,
                edge.measurement.child_distinct_keys,
                edge.measurement.parent_rows_with_value,
                edge.measurement.parent_distinct_keys,
                edge.measurement.orphan_keys,
                edge.cross_database,
            ),
        )
    for site in projection.code_sites:
        connection.execute(
            """
            INSERT INTO workspace_table_relation_code_sites (
                id, edge_id, kind, file_path, method_name, snippet, position
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4().hex,
                site.edge_id,
                site.kind,
                site.file_path,
                site.method_name,
                site.snippet,
                site.position,
            ),
        )
    for site in projection.write_sites:
        connection.execute(
            """
            INSERT INTO workspace_table_write_sites (
                id, generation_id, database_key, schema_name, table_name,
                kind, file_path, method_name, snippet, position
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4().hex,
                site.generation_id,
                site.database_key,
                site.schema_name,
                site.table_name,
                site.kind,
                site.file_path,
                site.method_name,
                site.snippet,
                site.position,
            ),
        )
    for site in projection.update_sites:
        connection.execute(
            """
            INSERT INTO workspace_table_update_sites (
                id, generation_id, database_key, schema_name, table_name,
                kind, file_path, method_name, snippet, position
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4().hex,
                site.generation_id,
                site.database_key,
                site.schema_name,
                site.table_name,
                site.kind,
                site.file_path,
                site.method_name,
                site.snippet,
                site.position,
            ),
        )


def _resolve_workspace(connection: psycopg.Connection[Any], workspace_id: str | None) -> str:
    if workspace_id:
        row = connection.execute(
            "SELECT id FROM workspaces WHERE id = %s",
            (workspace_id,),
        ).fetchone()
        if row is None:
            raise SystemExit(f"找不到工作空间 {workspace_id}")
        return str(row[0])
    rows = connection.execute("SELECT id, name FROM workspaces ORDER BY name").fetchall()
    if not rows:
        raise SystemExit("库里没有工作空间，请先注册工作空间再执行种子脚本")
    if len(rows) > 1:
        names = "，".join(f"{row[1]}（{row[0]}）" for row in rows)
        raise SystemExit(f"有多个工作空间，请用 --workspace 指定：{names}")
    return str(rows[0][0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="写入表关联示例数据")
    parser.add_argument("--workspace", default=None, help="工作空间 ID，只有一个时可省略")
    parser.add_argument(
        "--environment",
        default="uat",
        help="产生这份唯一表关联快照的环境，默认 uat",
    )
    args = parser.parse_args(argv)

    database_url = Settings().database_url
    if not database_url:
        raise SystemExit("CONTEXT_ROUTER_DATABASE_URL 未配置，无法写入示例数据")

    with psycopg.connect(database_url) as connection:
        workspace_id = _resolve_workspace(connection, args.workspace)
        projection = build_seed_projection(
            workspace_id=workspace_id,
            environment=args.environment,
        )
        insert_projection(connection, projection)
        connection.commit()

    generation = projection.generation
    disagreeing = sum(
        1 for edge in projection.edges if edge.code_cardinality != edge.db_cardinality
    )
    dangling = sum(1 for edge in projection.edges if edge.measurement.orphan_keys > 0)
    print(
        f"已为工作空间 {workspace_id}（{args.environment}）写入表关联示例数据："
        f"{len(projection.tables)} 张表、{generation.edge_count} 条关系"
        f"（页面展示 {generation.relation_count} 条，"
        f"死列不展示 {generation.hidden_count} 条），"
        f"其中两个维度结论不一致 {disagreeing} 条，"
        f"存在指不到父行的键 {dangling} 条，"
        f"代码点位 {len(projection.code_sites)} 处，"
        f"表级插入入口 {len(projection.write_sites)} 处，"
        f"表级更新入口 {len(projection.update_sites)} 处。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
