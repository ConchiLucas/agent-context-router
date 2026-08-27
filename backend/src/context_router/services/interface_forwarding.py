from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from context_router.schemas.interface_forwarding import (
    InterfaceForwardingEnvironmentWrite,
    InterfaceForwardingExecute,
    InterfaceForwardingIdentityWrite,
    InterfaceForwardingImport,
    InterfaceForwardingLogWrite,
    InterfaceSemanticsWrite,
)


class InterfaceForwardingError(RuntimeError):
    pass


class InterfaceForwardingService:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url

    @staticmethod
    def _coalesce_interface_name(
        name: str,
        *,
        operation_id: str = "",
        summary: str = "",
        path: str = "",
        method: str = "",
        controller_description: str = "",
    ) -> str:
        if not name:
            name = f"{method.upper()} {path}".strip()
        if not name:
            return ""

        # ``/basic-api`` is a generated Swagger group whose operations usually
        # have no summary.  Its Controller tags are implementation names, so a
        # path-aware name is more reliable than the generic Controller fallback
        # (for example, POST ``getById`` must not become “新增”).
        declaration_api_name = InterfaceForwardingService._derive_declaration_api_name(path)
        if declaration_api_name:
            return declaration_api_name

        order_api_name = InterfaceForwardingService._derive_order_api_name(path)
        if order_api_name:
            return order_api_name

        line_api_name = InterfaceForwardingService._derive_line_api_name(path)
        if line_api_name:
            return line_api_name

        shipping_api_name = InterfaceForwardingService._derive_shipping_api_name(path)
        if shipping_api_name:
            return shipping_api_name

        settlement_api_name = InterfaceForwardingService._derive_settlement_api_name(path)
        if settlement_api_name:
            return settlement_api_name

        trace_api_name = InterfaceForwardingService._derive_trace_api_name(path)
        if trace_api_name:
            return trace_api_name

        railway_api_name = InterfaceForwardingService._derive_railway_api_name(path)
        if railway_api_name:
            return railway_api_name

        operation_api_name = InterfaceForwardingService._derive_operation_api_name(path)
        if operation_api_name:
            return operation_api_name

        highway_api_name = InterfaceForwardingService._derive_highway_api_name(path)
        if highway_api_name:
            return highway_api_name

        remaining_api_name = InterfaceForwardingService._derive_remaining_api_name(path)
        if remaining_api_name:
            return remaining_api_name

        basic_api_name = InterfaceForwardingService._derive_basic_api_name(path)
        if basic_api_name:
            return basic_api_name

        overrides = {"download_11": "下载附件", "upload_11": "上传附件"}
        normalized_name = str(name).strip()
        if normalized_name in overrides:
            return overrides[normalized_name]

        normalized_operation_id = str(operation_id).strip()
        if normalized_operation_id in overrides:
            return overrides[normalized_operation_id]

        normalized_summary = str(summary).strip()
        if InterfaceForwardingService._contains_chinese(normalized_summary):
            return normalized_summary

        if InterfaceForwardingService._contains_chinese(normalized_name):
            return normalized_name

        lowered_path = str(path).lower()
        lowered_operation_id = normalized_operation_id.lower()
        lowered_name = str(name).lower()
        lowered_summary = normalized_summary.lower()
        if lowered_operation_id.startswith("download_") and "attachment" in lowered_path:
            return "下载附件"
        if lowered_operation_id.startswith("upload_") and "attachment" in lowered_path:
            return "上传附件"

        subject = InterfaceForwardingService._derive_subject_cn(
            normalized_name,
            normalized_operation_id,
            path,
            str(controller_description),
        )
        action = InterfaceForwardingService._derive_action_cn(
            str(method),
            lowered_summary,
            lowered_operation_id,
            lowered_path,
            lowered_name,
        )
        if action:
            if subject:
                return f"{action}{subject}"
            return action

        if subject:
            return subject

        return normalized_name

    @staticmethod
    def _derive_basic_api_name(path: str) -> str:
        parts = [part for part in str(path).split("/") if part and not part.startswith("{")]
        if not parts or parts[0] != "basic-api" or len(parts) < 3:
            return ""

        ignored = {"admin", "portal", "noAuth", "remote", "api", "system"}
        business_parts = [part for part in parts[1:-1] if part not in ignored]
        action_parts = parts[-1:]
        if len(parts) >= 4 and parts[-2] in {"masterGoods", "packageUnit", "routeProduct"}:
            action_parts = parts[-2:]
            business_parts = business_parts[:-1]

        resource_path = "/".join(part for part in parts[1:] if part not in ignored)
        direct_names = {
            "division/getDivisionId/byName": "按名称查询分区 ID",
        }
        if direct_name := direct_names.get(resource_path):
            return direct_name

        subject_key = "/".join(business_parts)
        subjects = {
            "address": "地址",
            "basePrice": "货物基础价格",
            "business": "业务主体",
            "cargo": "货物",
            "cargo/category": "货物类别",
            "cargoExternal": "外部货物",
            "config": "费用配置",
            "dispatchManifest": "调度清单",
            "division": "分区",
            "driver": "司机",
            "inventorySummary": "库存汇总",
            "outboundBox": "装箱记录",
            "port": "港口",
            "productArchive": "商品档案",
            "ship": "船舶",
            "shipOwner": "船东",
            "site/fee": "站点费用",
            "site/feeItem": "站点费用项",
            "site/feeItemRange": "站点费用项区间",
            "template": "模板",
            "track": "运输轨迹",
            "userDivision": "用户分区",
            "vehicle": "车辆",
            "warehouse": "仓库",
            "administrativeRegion": "行政区划",
            "rolePermission": "角色权限",
        }
        subject = subjects.get(subject_key, "")
        if not subject:
            # CommonController contains utility endpoints rather than a single
            # business resource, therefore each path has an explicit label.
            common_names = {
                "common/administrativeRegion/getChildRegionList": "查询下级行政区划",
                "common/amapSecret": "获取高德地图密钥",
                "common/getTemplateFileUrl": "获取模板文件地址",
                "common/getTempleFileUrl": "获取模板文件地址",
            }
            return common_names.get(resource_path, "")

        action_key = "/".join(action_parts)
        full_names = {
            ("productArchive", "packageUnit/default"): "设置商品档案包装单位默认状态",
            ("productArchive", "packageUnit/status"): "更新商品档案包装单位状态",
            ("driver", "carrierPage"): "分页查询承运商司机",
            ("driver", "carrierSave"): "保存承运商司机",
            ("userDivision", "getDivisionByUser"): "查询用户所属分区",
            ("userDivision", "getDivisionUser"): "查询分区用户",
            ("userDivision", "getUser"): "查询用户",
            ("userDivision", "updateUserIds"): "更新分区用户",
            ("site/fee", "queryFeeItems"): "查询站点费用项",
            ("site/fee", "getCargoConfig"): "查询站点货物配置",
            ("site/fee", "findCargoConfig"): "查询站点货物配置",
            ("site/fee", "routeProduct/getByIdAndSiteType"): "按站点类型查询线路货物",
            ("site/fee", "routeProduct/queryFeeItems"): "查询线路货物费用项",
            ("cargo", "packageUnits"): "查询货物包装单位",
            ("cargo", "saveFromMaster"): "从主数据保存货物",
            ("division", "byName"): "按名称查询分区 ID",
            ("port", "companies"): "查询企业港口",
            ("port", "importPort"): "导入港口",
            ("site/fee", "findAllSite"): "查询全部站点",
        }
        if full_name := full_names.get((subject_key, action_key)):
            return full_name

        actions = {
            "page": "分页查询",
            "pageList": "分页查询",
            "detail": "查询详情",
            "getById": "按 ID 查询",
            "getByIds": "按 ID 批量查询",
            "getByIdsList": "按 ID 批量查询",
            "getByList": "按条件查询",
            "getByCode": "按编码查询",
            "getByPortName": "按港口名称查询",
            "getByShipName": "按船名查询",
            "getVehicleDetail": "查询详情",
            "getVehicleList": "查询列表",
            "findAll": "查询全部",
            "findByCondition": "按条件查询",
            "findByCargoName": "按货物名称查询",
            "findById": "按 ID 查询",
            "findByIds": "按 ID 批量查询",
            "list": "查询列表",
            "save": "保存",
            "saveOrUpdate": "保存",
            "saveOrEdit": "保存",
            "batchSave": "批量保存",
            "copyAdd": "复制新增",
            "delete": "删除",
            "deleteByIds": "批量删除",
            "deleteIds": "批量删除",
            "changeEnable": "启用",
            "changeDisable": "停用",
            "updateStatus": "更新状态",
            "import": "导入",
            "masterGoods/page": "分页查询主数据",
            "selectCargoPage": "分页选择",
            "cargoPage": "分页查询货物",
            "categoryPage": "分页查询货物类别",
            "getMenuTreeByUserId": "查询用户菜单树",
            "getChildRegionList": "查询下级区域",
            "getDivisionById": "按 ID 查询",
            "getDivisionByIds": "按 ID 批量查询",
            "getDivisionName": "查询名称",
            "getDivisionSelectTree": "查询选择树",
            "queryDivisionTree": "查询分区树",
            "getDivisionByUser": "查询用户分区",
            "getDivisionUser": "查询分区用户",
            "getUser": "查询用户",
            "updateUserIds": "更新用户",
            "queryFeeItems": "查询费用项",
            "getCargoConfig": "查询货物配置",
            "findCargoConfig": "查询货物配置",
            "getByIdAndSiteType": "按站点类型查询",
            "queryByBoxNos": "按箱码查询",
            "carrierMapTrack": "查询承运商运输轨迹",
            "modifyRelateContractCount": "更新关联合同数量",
            "getByInfo": "按条件查询",
        }
        action = actions.get(action_key)
        return f"{action}{subject}" if action else ""

    @staticmethod
    def _derive_declaration_api_name(path: str) -> str:
        parts = [part for part in str(path).split("/") if part and not part.startswith("{")]
        if not parts or parts[0] != "declaration-api" or len(parts) < 3:
            return ""

        ignored = {"admin", "portal", "api", "system"}
        logical_parts = [part for part in parts[1:] if part not in ignored]
        if not logical_parts:
            return ""
        subject_key = logical_parts[0]
        action_key = "/".join(logical_parts[1:])
        subjects = {
            "attachment": "附件",
            "attribute": "订单货物属性",
            "basicInformation": "基础信息",
            "cargo": "订单货物",
            "commodityBasicData": "商品基础数据",
            "commodityCatalog": "商品目录",
            "commodity": "商品",
            "container": "订单集装箱",
            "declare": "订单申报信息",
            "document": "订单单证",
            "enterprise": "检疫企业",
            "entrust": "委托单",
            "order": "报关订单",
            "origin": "原产地信息",
            "quarantine": "订单检疫信息",
            "transport": "订单运输信息",
            "rolePermission": "角色权限",
        }
        subject = subjects.get(subject_key, "")
        if not subject:
            return ""

        direct_names = {
            ("attachment", "downLoad"): "下载附件",
            ("attachment", "preview/url"): "获取附件预览地址",
            ("attachment", "saveAndUploadAttachment"): "保存并上传附件",
            ("attachment", "uploadAndSave"): "上传并保存附件",
            ("basicInformation", "findGroupByList"): "分组查询基础信息",
            ("basicInformation", "importCiq"): "导入 CIQ 基础信息",
            ("basicInformation", "importCommodityBasicDataType"): "导入商品基础数据类型",
            ("basicInformation", "importDeclarationElement"): "导入申报要素",
            ("basicInformation", "importDistrict"): "导入地区信息",
            ("commodityBasicData", "findGroupByList"): "分组查询商品基础数据",
            ("commodityBasicData", "importCommodityBasicData"): "导入商品基础数据",
            ("commodity", "exportCommodity"): "导出商品",
            ("commodity", "importCommodity"): "导入商品",
            ("commodity", "getChapterInfoByCode"): "按编码查询商品章节信息",
            ("commodity", "queryCommodityTree"): "查询商品树",
            ("entrust", "approve"): "审批委托单",
            ("entrust", "reject"): "驳回委托单",
            ("entrust", "copy"): "复制委托单",
            ("entrust", "getEntrustInfo"): "查询委托单信息",
            ("order", "copy"): "复制报关订单",
            ("order", "declareOrder"): "申报报关订单",
            ("order", "getDeclareDetailById"): "查询订单申报详情",
            ("order", "getMakeDetailById"): "查询订单制单详情",
            ("order", "saveDeclareDetail"): "保存订单申报详情",
            ("order", "transportOrderPage"): "分页查询运输订单",
            ("origin", "importOrigin"): "导入原产地信息",
            ("rolePermission", "getMenuTreeByUserId"): "查询用户菜单树",
        }
        if direct_name := direct_names.get((subject_key, action_key)):
            return direct_name

        actions = {
            "page": "分页查询",
            "getById": "按 ID 查询",
            "deleteByIds": "批量删除",
            "save": "保存",
            "saveOrUpdate": "保存",
            "list": "查询列表",
            "updateStatus": "更新状态",
        }
        action = actions.get(action_key)
        return f"{action}{subject}" if action else ""

    @staticmethod
    def _derive_order_api_name(path: str) -> str:
        parts = [part for part in str(path).split("/") if part and not part.startswith("{")]
        if not parts or parts[0] != "order-api" or len(parts) < 3:
            return ""

        ignored = {"admin", "portal", "api", "dsly", "common"}
        logical_parts = [part for part in parts[1:] if part not in ignored]
        resource_subjects = {
            "entrustedOrderSettlement/orderSettlement": "委托订单结算",
            "booking/applicationConfirm": "订舱申请确认",
            "booking/application": "订舱申请",
            "entrusted/cargoCharge": "委托货物费用",
            "entrusted/platformWarehouse": "平台仓库",
            "entrusted/quote": "委托报价",
            "entrustedOrder": "委托订单",
            "outboundBox": "装箱记录",
            "outboundOrder": "出库订单",
            "workPlan": "作业计划",
            "order/cargo": "订单货物",
            "attachment": "订单附件",
            "container": "订单集装箱",
            "entrusted": "委托需求",
            "file": "订单文件",
            "oder/node": "订单节点",
            "relate": "委托订单关联",
        }
        joined = "/".join(logical_parts)
        resource_key = next(
            (
                key
                for key in sorted(resource_subjects, key=len, reverse=True)
                if joined == key or joined.startswith(f"{key}/")
            ),
            "",
        )
        if not resource_key:
            return ""
        subject = resource_subjects[resource_key]
        action_key = joined[len(resource_key) :].lstrip("/")

        direct_names = {
            ("attachment", "downloadUrlByFileId"): "按文件 ID 获取附件下载地址",
            ("attachment", "preview/url"): "获取附件预览地址",
            ("attachment", "preview"): "预览附件",
            ("attachment", "upload"): "上传附件",
            ("booking/application", "confirm"): "确认订舱申请",
            ("booking/application", "generate"): "生成订舱申请",
            ("booking/application", "applicationConfirm/save"): "保存订舱申请确认",
            ("booking/application", "entrusted/deleteByIds"): "批量删除订舱申请委托单",
            ("booking/application", "entrusted/save"): "保存订舱申请委托单",
            ("entrusted", "ensureCargoCategory"): "确认委托需求货物类别",
            ("entrusted", "generatePlanFromContract"): "根据合同生成作业计划",
            ("entrusted", "getFeeConfigPage"): "分页查询费用配置",
            ("entrusted", "getQuoteById"): "按 ID 查询委托报价",
            ("entrusted", "getSettlementInfo"): "查询结算信息",
            ("entrusted", "getUserAllPage"): "分页查询用户",
            ("entrusted", "goods/canModify"): "判断主数据商品是否允许修改",
            ("entrusted", "queryFeeItems"): "查询费用项",
            ("entrusted", "routeRailwayGetById"): "按 ID 查询铁路线路",
            ("entrusted", "shipper/page"): "分页查询托运人",
            ("entrusted", "getPortalPage"): "分页查询门户委托需求",
            ("entrusted", "saveEntrusted"): "保存委托需求",
            ("entrustedOrder", "booking/page"): "分页查询订舱申请",
            ("entrustedOrder", "cargo/page"): "分页查询委托订单货物",
            ("entrustedOrder", "cargoPageList"): "分页查询委托订单货物",
            ("entrustedOrder", "carrierPage"): "分页查询承运商",
            ("entrustedOrder", "changeCarrier"): "变更承运商",
            ("entrustedOrder", "contractPage"): "分页查询合同",
            ("entrustedOrder", "deleteCarrierOrderAttachment"): "删除承运商订单附件",
            ("entrustedOrder", "findOrderContainerList"): "查询订单集装箱列表",
            ("entrustedOrder", "findWhole"): "查询完整委托订单",
            ("entrustedOrder", "generateTransportOrder"): "生成运输订单",
            ("entrustedOrder", "getCargoList"): "查询订单货物列表",
            ("entrustedOrder", "getCarrierOrderAttachmentList"): "查询承运商订单附件列表",
            ("entrustedOrder", "getDocumentInfo"): "查询订单单证信息",
            ("entrustedOrder", "getFileIdByContractNo"): "按合同号查询文件 ID",
            ("entrustedOrder", "getOrderattachmentList"): "查询订单附件列表",
            ("entrustedOrder", "getOrderSplitSegments"): "查询订单拆分段",
            ("entrustedOrder", "getTraceEntrustedDetail"): "查询委托订单轨迹详情",
            ("entrustedOrder", "listByEntrustedOrderNo"): "按委托订单号查询",
            ("entrustedOrder", "orderattachmentUpload"): "上传订单附件",
            ("entrustedOrder", "OrderDownloadAttachment"): "下载订单附件",
            ("entrustedOrder", "shipperPage"): "分页查询托运人",
            ("entrustedOrder", "sitePage"): "分页查询站点",
            ("entrustedOrder", "uploadCarrierOrderAttachment"): "上传承运商订单附件",
            ("entrustedOrder", "withdrawalEntrustedOrder"): "撤回委托订单",
            ("entrustedOrder", "withdrawCarrierOrder"): "撤回承运商订单",
            ("entrustedOrder", "entrustedOrderSign"): "签署委托订单",
            ("entrustedOrder", "warehouseSource"): "查询委托订单数据来源及关联出库订单",
            ("entrusted/quote", "approval"): "审批委托报价",
            ("entrusted/quote", "approvalPage"): "分页查询待审批委托报价",
            ("entrusted/quote", "cancelApproval"): "取消委托报价审批",
            ("entrusted/quote", "edit"): "编辑委托报价",
            ("entrusted/quote", "getByEntrustedId"): "按委托需求 ID 查询报价",
            ("entrusted/quote", "getEntrustedQuoteById"): "按 ID 查询委托报价",
            ("entrusted/quote", "quoteApprove"): "审批委托报价",
            ("entrusted/quote", "quoteReject"): "驳回委托报价",
            ("entrusted/quote", "shipper/approve"): "审批托运人报价",
            ("entrusted/quote", "shipper/reject"): "驳回托运人报价",
            ("file", "preview"): "预览订单文件",
            ("outboundOrder", "options"): "查询出库订单筛选项",
            ("workPlan", "approve"): "审批作业计划",
            ("workPlan", "cancel"): "取消作业计划",
            ("workPlan", "workDistribute"): "分配作业计划",
        }
        if direct_name := direct_names.get((resource_key, action_key)):
            return direct_name

        actions = {
            "page": "分页查询",
            "pageList": "分页查询",
            "getById": "按 ID 查询",
            "getByIds": "按 ID 批量查询",
            "getList": "查询列表",
            "deleteByIds": "批量删除",
            "save": "保存",
            "preview": "预览",
        }
        action = actions.get(action_key)
        return f"{action}{subject}" if action else ""

    @staticmethod
    def _derive_line_api_name(path: str) -> str:
        parts = [part for part in str(path).split("/") if part and not part.startswith("{")]
        if not parts or parts[0] != "line-api" or len(parts) < 3:
            return ""

        ignored = {"admin", "portal", "api", "system", "noAuth", "remote", "delegate"}
        logical_parts = [part for part in parts[1:] if part not in ignored]
        resource_subjects = {
            "approval/history": "审批历史",
            "approval/user": "审批用户",
            "route/cargoChargeRange": "线路货物费用区间",
            "route/cargoCharge": "线路货物费用",
            "route/railwayStation": "线路铁路站点",
            "route/snapshotQuote": "线路快照报价",
            "route/product": "线路产品",
            "routeInquiryQuotePlan": "线路询报价方案",
            "routeInquiry": "线路询价",
            "rolePermission": "角色权限",
            "attachment": "附件",
            "route": "线路",
            "station": "站点",
        }
        joined = "/".join(logical_parts)
        resource_key = next(
            (
                key
                for key in sorted(resource_subjects, key=len, reverse=True)
                if joined == key or joined.startswith(f"{key}/")
            ),
            "",
        )
        if not resource_key:
            return ""
        subject = resource_subjects[resource_key]
        action_key = joined[len(resource_key) :].lstrip("/")

        direct_names = {
            ("rolePermission", "getMenuTreeByUserId"): "查询用户菜单树",
            ("attachment", "preview/url"): "获取附件预览地址",
            ("attachment", "preview"): "预览附件",
            ("route", "approval/page"): "分页查询待审批线路",
            ("route", "checkRelevanceDelete"): "校验线路是否可删除",
            ("route", "checkRelevanceDisable"): "校验线路是否可停用",
            ("route", "getFeeConfigPage"): "分页查询线路费用配置",
            ("route", "getFileIdByContractNo"): "按合同号查询文件 ID",
            ("route", "getPriceByCondition"): "按条件查询线路价格",
            ("route", "getRailwayLineList"): "查询铁路线路列表",
            ("route", "getRailwayValidCarrierList"): "查询铁路有效承运商",
            ("route", "getTemplateFileUrl"): "获取线路模板文件地址",
            ("route", "getTempleFileUrl"): "获取线路模板文件地址",
            ("route", "getTransportUnitByRouteIds"): "按线路查询运输单位",
            ("route", "getValidContractByClientId"): "按客户查询有效合同",
            ("route", "routeRailwayGetById"): "查询铁路线路详情",
            ("route", "routeRailwayPage"): "分页查询铁路线路",
            ("route", "saveRouteRailway"): "保存铁路线路",
            ("route", "selectCargoCategoryPage"): "分页选择货物类别",
            ("route", "selectCargoPage"): "分页选择货物",
            ("route", "selectPage"): "分页选择线路",
            ("route", "selectRailwayLine"): "选择铁路线路",
            ("route", "sitePage"): "分页查询站点",
            ("route", "validCarrierPage"): "分页查询有效承运商",
            ("routeInquiry", "associationContract"): "关联合同",
            ("routeInquiry", "entrustedNoPage"): "分页查询委托单号",
            ("routeInquiry", "getCategoryByInquiryId"): "按询价 ID 查询货物类别",
            ("routeInquiry", "getRouteInquiryLineById"): "查询线路询价详情",
            ("routeInquiry", "portPage"): "分页查询港口",
            ("routeInquiry", "stationPage"): "分页查询站点",
            ("routeInquiry", "terminateInquiry"): "终止线路询价",
            ("routeInquiry", "validCarrierPage"): "分页查询有效承运商",
            ("routeInquiry", "listForPortalIsUrgent"): "查询紧急线路询价",
            ("routeInquiry", "pageForPortal"): "分页查询门户线路询价",
            ("routeInquiryQuotePlan", "getByPlanId"): "按方案 ID 查询询报价方案",
            ("routeInquiryQuotePlan", "getByPlanIdForPortal"): "按方案 ID 查询询报价方案",
            ("routeInquiryQuotePlan", "getByRouteIdForPortal"): "按线路 ID 查询询报价方案",
            ("routeInquiryQuotePlan", "deletePlanByIdsForPortal"): "批量删除询报价方案",
            ("routeInquiryQuotePlan", "deleteRouteByIdForPortal"): "删除询报价方案线路",
            ("routeInquiryQuotePlan", "pageForPortal"): "分页查询门户询报价方案",
            ("routeInquiryQuotePlan", "saveForPortal"): "保存询报价方案",
            ("routeInquiryQuotePlan", "saveReQuoteForPortal"): "保存重新报价方案",
            ("routeInquiryQuotePlan", "saveRouteForPortal"): "保存询报价方案线路",
            ("routeInquiryQuotePlan", "updateRouteForPortal"): "更新询报价方案线路",
            ("routeInquiryQuotePlan", "updatePlanStatus"): "更新询报价方案状态",
            ("route/product", "findWhole"): "查询完整线路产品",
            ("route/product", "getByIdAndSiteType"): "按站点类型查询线路产品",
            ("route/product", "getRecommendRoute"): "查询推荐线路",
            ("route/product", "getRouteList"): "查询线路列表",
            ("route/product", "queryFeeItems"): "查询线路产品费用项",
            ("route/product", "reverRouteProduct"): "撤销线路产品",
            ("route/product", "saveSnapshot"): "保存线路产品快照",
            ("route/product", "validate/contract"): "校验线路产品合同",
            ("route/product", "validRevertProduct"): "校验线路产品是否可撤销",
            ("route/product", "findByProductNo"): "按产品编号查询线路产品",
            ("route/product", "quoteSuccess"): "确认线路产品报价成功",
            ("route/product", "frequentlyLine"): "查询常用线路",
            ("route/product", "hotLine"): "查询热门线路",
            ("route/product", "otherLine"): "查询其他线路",
            ("route/railwayStation", "getRailwayStationByRouteNo"): "按线路编号查询铁路站点",
            ("station", "findAllData"): "查询全部站点数据",
            ("station", "getStationById"): "按 ID 查询站点",
            ("station", "getStationListByStationNames"): "按站点名称查询站点列表",
            ("station", "getTemplateFileUrl"): "获取站点模板文件地址",
            ("station", "getTempleFileUrl"): "获取站点模板文件地址",
            ("station", "importStation"): "导入站点",
            ("station", "insert"): "新增站点",
            ("station", "updateFeeConfigByIds"): "批量更新站点费用配置",
            ("station", "updateStationStatusByIds"): "批量更新站点状态",
        }
        if direct_name := direct_names.get((resource_key, action_key)):
            return direct_name

        actions = {
            "page": "分页查询",
            "pageList": "分页查询",
            "getById": "按 ID 查询",
            "getByIds": "按 ID 批量查询",
            "deleteByIds": "批量删除",
            "save": "保存",
            "list": "查询列表",
            "updateStatus": "更新状态",
            "import": "导入",
        }
        action = actions.get(action_key)
        return f"{action}{subject}" if action else ""

    @staticmethod
    def _derive_shipping_api_name(path: str) -> str:
        parts = [part for part in str(path).split("/") if part and not part.startswith("{")]
        if not parts or parts[0] != "shipping-api" or len(parts) < 3:
            return ""

        ignored = {"admin", "portal", "remote"}
        logical_parts = [part for part in parts[1:] if part not in ignored]
        resource_subjects = {
            "attachment": "运输附件",
            "cargo": "运输货物",
            "carrierOrder": "承运商订单",
            "dispatchOrder": "调度订单",
            "record": "运输记录",
        }
        resource_key = logical_parts[0] if logical_parts else ""
        subject = resource_subjects.get(resource_key, "")
        if not subject:
            return ""
        action_key = "/".join(logical_parts[1:])
        direct_names = {
            ("attachment", "downLoad"): "下载运输附件",
            ("attachment", "preview/url"): "获取运输附件预览地址",
            ("attachment", "preview"): "预览运输附件",
            ("attachment", "getContractAttachmentList"): "查询合同附件列表",
            ("attachment", "getDocumentList"): "查询单证附件列表",
            ("attachment", "deleteByList"): "按列表删除运输附件",
            ("attachment", "upload"): "上传运输附件",
            ("attachment", "uploadAndSave"): "上传并保存运输附件",
            ("cargo", "getCargoListByCarrierOrderNo"): "按承运商订单号查询货物列表",
            ("cargo", "getCargoListByDispatchOrderNo"): "按调度订单号查询货物列表",
            ("carrierOrder", "batchCreateCarrierOrder"): "批量创建承运商订单",
            ("carrierOrder", "batchDispatchOrder"): "批量调度承运商订单",
            ("carrierOrder", "changeCarrierOrderInfo"): "变更承运商订单信息",
            ("carrierOrder", "forceCloseOrder"): "强制关闭承运商订单",
            ("carrierOrder", "getCarrierInfoList"): "查询承运商信息列表",
            ("carrierOrder", "getDispatchInfoList"): "查询调度信息列表",
            ("carrierOrder", "getDispatchDetail"): "查询调度详情",
            ("carrierOrder", "getFileIdByContractNo"): "按合同号查询文件 ID",
            ("carrierOrder", "listByEntrustedOrderNo"): "按委托订单号查询承运商订单",
            ("carrierOrder", "settlementCarrierPage"): "分页查询承运商结算订单",
            ("carrierOrder", "withdrawCarrierOrder"): "撤回承运商订单",
            ("dispatchOrder", "customPage"): "分页查询客户调度订单",
            ("dispatchOrder", "documentPage"): "分页查询调度订单单证",
            ("dispatchOrder", "getDispatchInfo"): "查询调度信息",
            ("dispatchOrder", "getDocumentById"): "按 ID 查询调度单证",
            ("dispatchOrder", "getManifestDetail"): "查询舱单详情",
            ("dispatchOrder", "getManifestPage"): "分页查询舱单",
            ("dispatchOrder", "pageByCarrierNo"): "按承运商编号分页查询调度订单",
            ("dispatchOrder", "settlementDispatchPage"): "分页查询调度结算订单",
            ("dispatchOrder", "sign"): "签收调度订单",
            ("dispatchOrder", "getLoadInfo"): "查询装货信息",
            ("dispatchOrder", "getRedispatchDetail"): "查询重新调度详情",
            ("dispatchOrder", "getUnloadInfo"): "查询卸货信息",
            ("dispatchOrder", "load"): "装货",
            ("dispatchOrder", "modifyLoadInfo"): "修改装货信息",
            ("dispatchOrder", "modifyUnloadInfo"): "修改卸货信息",
            ("dispatchOrder", "redispatch"): "重新调度",
            ("dispatchOrder", "unload"): "卸货",
            ("record", "getListByDispatchOrderNo"): "按调度订单号查询运输记录",
        }
        if direct_name := direct_names.get((resource_key, action_key)):
            return direct_name

        actions = {
            "page": "分页查询",
            "getById": "按 ID 查询",
            "deleteByIds": "批量删除",
            "saveOrUpdate": "保存",
        }
        action = actions.get(action_key)
        return f"{action}{subject}" if action else ""

    @staticmethod
    def _derive_settlement_api_name(path: str) -> str:
        parts = [part for part in str(path).split("/") if part and not part.startswith("{")]
        if not parts or parts[0] != "settlement-api" or len(parts) < 3:
            return ""

        logical_parts = [part for part in parts[1:] if part not in {"admin", "portal"}]
        resource_subjects = {
            "operation/fee": "运营费用",
            "account": "费用",
            "advancePayment": "垫付款",
            "attachment": "结算附件",
            "btExpense": "业务费用",
            "collection": "收款",
            "config": "结算费用配置",
            "log": "修改日志",
            "ownerFund": "货主资金",
            "ownerFundFlow": "货主资金流水",
            "payableBill": "应付账单",
            "paymentApply": "付款申请",
            "paymentapply": "付款申请",
            "paymentApplyHistory": "付款申请历史",
            "paymentConfirmation": "付款确认",
            "paymentRelation": "付款关系",
            "paymentrelation": "付款关系",
            "paymentVerification": "付款核销",
            "paymentverification": "付款核销",
            "prepayment": "预付款",
            "receiptConfirmation": "收款确认",
            "receiptconfirmation": "收款确认",
            "receiptVerification": "收款核销",
            "receiptverification": "收款核销",
            "receivableBill": "应收账单",
            "salesInvoice": "销售发票",
        }
        joined = "/".join(logical_parts)
        resource_key = next(
            (
                key
                for key in sorted(resource_subjects, key=len, reverse=True)
                if joined == key or joined.startswith(f"{key}/")
            ),
            "",
        )
        if not resource_key:
            return ""
        subject = resource_subjects[resource_key]
        action_key = joined[len(resource_key) :].lstrip("/")

        direct_names = {
            ("attachment", "downLoad"): "下载结算附件",
            ("attachment", "preview/url"): "获取结算附件预览地址",
            ("attachment", "preview"): "预览结算附件",
            ("attachment", "upload"): "上传结算附件",
            ("account", "mqCreateExpense"): "消息创建费用",
            ("account", "processExpenseBillId"): "处理费用账单 ID",
            ("account", "transportOrderPage"): "分页查询运输订单费用",
            ("advancePayment", "carrierOrderPage"): "分页查询承运商订单垫付款",
            ("btExpense", "createPayableBillByExpense"): "根据费用创建应付账单",
            ("btExpense", "createReceivableBillByExpense"): "根据费用创建应收账单",
            ("btExpense", "modifyLogPage"): "分页查询费用修改日志",
            ("btExpense", "processExpenseBillId"): "处理费用账单 ID",
            ("btExpense", "processReceivableExpenseBillId"): "处理应收费用账单 ID",
            ("collection", "batchConfirm"): "批量确认收款",
            ("operation/fee", "generateBillingOrder"): "生成运营费用结算单",
            ("operation/fee", "getInfo"): "查询运营费用信息",
            ("ownerFund", "shipperPage"): "分页查询托运人货主资金",
            ("paymentApply", "approve"): "审批付款申请",
            ("paymentConfirmation", "carrierPage"): "分页查询承运商付款确认",
            ("paymentConfirmation", "confirmVerification"): "确认付款核销",
            ("paymentConfirmation", "page/export"): "导出付款确认",
            ("prepayment", "batchCancelConfirm"): "批量取消确认预付款",
            ("prepayment", "batchConfirm"): "批量确认预付款",
            ("prepayment", "batchPaymentApply"): "批量发起付款申请",
            ("prepayment", "billPage"): "分页查询预付款账单",
            ("prepayment", "sumAppliedAmount"): "汇总已申请预付款金额",
            ("receiptConfirmation", "confirmVerification"): "确认收款核销",
            ("receiptConfirmation", "upload"): "上传收款确认附件",
            ("salesInvoice", "processExpenseBillId"): "处理销售发票费用账单 ID",
        }
        if direct_name := direct_names.get((resource_key, action_key)):
            return direct_name

        action_map = {
            "page": "分页查询",
            "getById": "按 ID 查询",
            "deleteByIds": "批量删除",
            "save": "保存",
            "saveOrUpdate": "保存",
            "batchCancelConfirmReconciliation": "批量取消确认对账",
            "batchCancelReconciliation": "批量取消对账",
            "batchConfirmReconciliation": "批量确认对账",
            "batchInitiateReconciliation": "批量发起对账",
            "batchRejectReconciliation": "批量驳回对账",
            "batchSubmitPayment": "批量提交付款",
            "createBillByExpense": "根据费用创建账单",
        }
        action = action_map.get(action_key)
        return f"{action}{subject}" if action else ""

    @staticmethod
    def _derive_trace_api_name(path: str) -> str:
        parts = [part for part in str(path).split("/") if part and not part.startswith("{")]
        if not parts or parts[0] != "trace-api" or len(parts) < 3:
            return ""
        logical_parts = [
            part for part in parts[1:] if part not in {"admin", "portal", "api", "system"}
        ]
        logical_path = "/".join(logical_parts)
        return {
            "rolePermission/getMenuTreeByUserId": "查询用户菜单树",
            "track/carrierMapTrack": "查询承运商地图轨迹",
            "track/dispatchDetail": "查询调度详情",
            "track/overview": "查询运输轨迹概览",
        }.get(logical_path, "")

    @staticmethod
    def _derive_railway_api_name(path: str) -> str:
        parts = [part for part in str(path).split("/") if part and not part.startswith("{")]
        if not parts or parts[0] != "railway-api" or len(parts) < 3:
            return ""
        logical_parts = [part for part in parts[1:] if part not in {"admin", "portal", "remote"}]
        resource_subjects = {
            "attachment": "铁路运输附件",
            "cargo": "铁路运输货物",
            "carrierOrder": "铁路承运商订单",
            "dispatchManifest": "铁路调度舱单",
            "dispatchOrderLine": "铁路调度订单线路",
            "dispatchOrder": "铁路调度订单",
            "railwayDailyPlan": "铁路日计划",
            "record": "铁路运输记录",
            "track": "铁路运输轨迹",
            "file": "铁路运输文件",
        }
        resource_key = logical_parts[0] if logical_parts else ""
        subject = resource_subjects.get(resource_key, "")
        if not subject:
            return ""
        action_key = "/".join(logical_parts[1:])
        direct_names = {
            ("attachment", "downLoad"): "下载铁路运输附件",
            ("attachment", "preview/url"): "获取铁路运输附件预览地址",
            ("attachment", "preview"): "预览铁路运输附件",
            ("attachment", "getContractAttachmentList"): "查询合同附件列表",
            ("attachment", "getDocumentList"): "查询单证附件列表",
            ("attachment", "deleteByList"): "按列表删除铁路运输附件",
            ("attachment", "upload"): "上传铁路运输附件",
            ("attachment", "uploadAndSave"): "上传并保存铁路运输附件",
            ("cargo", "getCargoListByCarrierOrderNo"): "按承运商订单号查询铁路运输货物列表",
            ("cargo", "getCargoListByDispatchOrderNo"): "按调度订单号查询铁路运输货物列表",
            ("carrierOrder", "batchCreateCarrierOrder"): "批量创建铁路承运商订单",
            ("carrierOrder", "batchDispatchOrder"): "批量调度铁路承运商订单",
            ("carrierOrder", "bindDailyPlan"): "绑定铁路日计划",
            ("carrierOrder", "bindDailyPlanPage"): "分页查询可绑定铁路日计划",
            ("carrierOrder", "dailyPlanInfo"): "查询铁路日计划信息",
            ("carrierOrder", "dailyPlanPage"): "分页查询铁路日计划",
            ("carrierOrder", "changeCarrierOrderInfo"): "变更铁路承运商订单信息",
            ("carrierOrder", "forceCloseOrder"): "强制关闭铁路承运商订单",
            ("carrierOrder", "getCarrierInfoList"): "查询承运商信息列表",
            ("carrierOrder", "getDispatchDetail"): "查询调度详情",
            ("carrierOrder", "getDispatchInfoList"): "查询调度信息列表",
            ("carrierOrder", "getFileIdByContractNo"): "按合同号查询文件 ID",
            ("carrierOrder", "getManifestInfoList"): "查询舱单信息列表",
            ("carrierOrder", "listByEntrustedOrderNo"): "按委托订单号查询铁路承运商订单",
            ("carrierOrder", "settlementCarrierPage"): "分页查询铁路承运商结算订单",
            ("carrierOrder", "withdrawCarrierOrder"): "撤回铁路承运商订单",
            ("dispatchManifest", "cargoPage"): "分页查询舱单货物",
            ("dispatchManifest", "categoryPage"): "分页查询舱单货物类别",
            ("dispatchOrder", "arrive"): "确认铁路调度订单到达",
            ("dispatchOrder", "batchGtDispatchOrder"): "批量处理铁路调度订单",
            ("dispatchOrder", "batchSaveOrUpdateLine"): "批量保存铁路调度订单线路",
            ("dispatchOrder", "customPage"): "分页查询客户铁路调度订单",
            ("dispatchOrder", "depart"): "确认铁路调度订单发车",
            ("dispatchOrder", "documentPage"): "分页查询铁路调度订单单证",
            ("dispatchOrder", "getContainerList"): "查询集装箱列表",
            ("dispatchOrder", "getDispatchInfo"): "查询调度信息",
            ("dispatchOrder", "getDocumentById"): "按 ID 查询调度单证",
            ("dispatchOrder", "getLineByDispatchOrderNo"): "按调度订单号查询线路",
            ("dispatchOrder", "getLinePage"): "分页查询调度订单线路",
            ("dispatchOrder", "getLineStationPage"): "分页查询调度订单线路站点",
            ("dispatchOrder", "getLoadInfo"): "查询装货信息",
            ("dispatchOrder", "getManifestDetail"): "查询铁路调度舱单详情",
            ("dispatchOrder", "getManifestPage"): "分页查询铁路调度舱单",
            ("dispatchOrder", "getRedispatchDetail"): "查询重新调度详情",
            ("dispatchOrder", "getStationPage"): "分页查询调度站点",
            ("dispatchOrder", "getUnloadInfo"): "查询卸货信息",
            ("dispatchOrder", "load"): "装货",
            ("dispatchOrder", "modifyLoadInfo"): "修改装货信息",
            ("dispatchOrder", "modifyUnloadInfo"): "修改卸货信息",
            ("dispatchOrder", "pageByCarrierNo"): "按承运商编号分页查询铁路调度订单",
            ("dispatchOrder", "railwayTransTrace"): "查询铁路运输轨迹",
            ("dispatchOrder", "redispatch"): "重新调度",
            ("dispatchOrder", "saveStation"): "保存调度站点",
            ("dispatchOrder", "settlementDispatchPage"): "分页查询铁路调度结算订单",
            ("dispatchOrder", "sign"): "签收铁路调度订单",
            ("dispatchOrder", "syncRailwayTrace"): "同步铁路运输轨迹",
            ("dispatchOrder", "unload"): "卸货",
            ("dispatchOrder", "updateDispatchManifest"): "更新铁路调度舱单",
            ("railwayDailyPlan", "bindPage"): "分页查询可绑定铁路日计划",
            ("railwayDailyPlan", "pageByCarrierNo"): "按承运商编号分页查询铁路日计划",
            ("record", "getListByDispatchOrderNo"): "按调度订单号查询铁路运输记录",
            ("track", "carrierMapTrack"): "查询承运商铁路地图轨迹",
            ("file", "preview"): "预览铁路运输文件",
        }
        if direct_name := direct_names.get((resource_key, action_key)):
            return direct_name
        action_map = {
            "page": "分页查询",
            "getById": "按 ID 查询",
            "deleteByIds": "批量删除",
            "save": "保存",
            "saveOrUpdate": "保存",
        }
        action = action_map.get(action_key)
        return f"{action}{subject}" if action else ""

    @staticmethod
    def _derive_operation_api_name(path: str) -> str:
        parts = [part for part in str(path).split("/") if part and not part.startswith("{")]
        if not parts or parts[0] != "operation-api" or len(parts) < 3:
            return ""
        logical_parts = [
            part for part in parts[1:] if part not in {"admin", "portal", "api", "inner"}
        ]
        resource_subjects = {
            "pickUpAppointment": "提货预约",
            "appointmentVehicle": "预约车辆",
            "appointment": "预约",
            "attachment": "运营附件",
            "container": "运营集装箱",
            "entrusted/quote/info": "委托报价信息",
            "entrusted/quote": "委托报价",
            "entrusted/quoteAudit": "委托报价审核",
            "entrustedOrder": "运营委托订单",
            "entrusted": "运营委托需求",
            "generalCargo": "普货",
            "workNode": "作业节点",
            "port": "港口",
        }
        joined = "/".join(logical_parts)
        resource_key = next(
            (
                key
                for key in sorted(resource_subjects, key=len, reverse=True)
                if joined == key or joined.startswith(f"{key}/")
            ),
            "",
        )
        if not resource_key:
            return ""
        subject = resource_subjects[resource_key]
        action_key = joined[len(resource_key) :].lstrip("/")
        direct_names = {
            ("entrusted/quote", ""): "发起委托报价",
            ("appointment", "acceptByIds"): "批量接受预约",
            ("appointment", "rejectedByIds"): "批量拒绝预约",
            ("attachment", "preview/url"): "获取运营附件预览地址",
            ("attachment", "preview"): "预览运营附件",
            ("attachment", "upload"): "上传运营附件",
            ("entrusted", "accept"): "接受运营委托需求",
            ("entrusted", "againQuote"): "重新报价",
            ("entrusted", "associationContract"): "关联合同",
            ("entrusted", "audit"): "审核运营委托需求",
            ("entrusted", "cancel"): "取消运营委托需求",
            ("entrusted", "cargo/category/page"): "分页查询货物类别",
            ("entrusted", "cargo/page"): "分页查询委托货物",
            ("entrusted", "contract/page"): "分页查询合同",
            ("entrusted", "createOrder"): "创建运营委托订单",
            ("entrusted", "entrustedPage"): "分页查询委托需求",
            ("entrusted", "entrustedQuoteInfoList"): "查询委托报价信息列表",
            ("entrusted", "getBizCommissionUrl"): "获取业务委托书地址",
            ("entrusted", "getByInfo"): "按条件查询运营委托需求",
            ("entrusted", "getByPortName"): "按港口名称查询委托需求",
            ("entrusted", "getCargoConfig"): "查询货物配置",
            ("entrusted", "notQuoted"): "查询未报价委托需求",
            ("entrusted", "quoteAudit/page"): "分页查询待审核委托报价",
            ("entrusted", "quote"): "发起委托报价",
            ("entrusted", "reject"): "拒绝运营委托需求",
            ("entrusted", "updateEntrustedStatus"): "更新委托需求状态",
            ("entrustedOrder", "acceptByIds"): "批量接受运营委托订单",
            ("entrustedOrder", "applicationFeeStatusChange"): "变更申请费用状态",
            ("entrustedOrder", "batchSave"): "批量保存运营委托订单",
            ("entrustedOrder", "findByList"): "按列表查询运营委托订单",
            ("entrustedOrder", "getBizCommissionUrl"): "获取业务委托书地址",
            ("entrustedOrder", "getByInfo"): "按条件查询运营委托订单",
            ("entrustedOrder", "pageSynergy"): "分页查询协同委托订单",
            ("entrustedOrder", "rejectedByIds"): "批量拒绝运营委托订单",
            ("workNode", "getByOrderId"): "按订单 ID 查询作业节点",
            ("appointmentVehicle", "deleteByAppointmentId"): "按预约删除车辆",
        }
        if direct_name := direct_names.get((resource_key, action_key)):
            return direct_name
        action_map = {
            "page": "分页查询",
            "getById": "按 ID 查询",
            "deleteByIds": "批量删除",
            "save": "保存",
            "update": "更新",
        }
        action = action_map.get(action_key)
        return f"{action}{subject}" if action else ""

    @staticmethod
    def _derive_highway_api_name(path: str) -> str:
        parts = [part for part in str(path).split("/") if part and not part.startswith("{")]
        if not parts or parts[0] != "highway-api" or len(parts) < 3:
            return ""
        logical_parts = [part for part in parts[1:] if part not in {"admin", "portal", "remote"}]
        subjects = {
            "attachment": "公路运输附件",
            "cargo": "公路运输货物",
            "carrierOrder": "公路承运商订单",
            "dispatchOrder": "公路调度订单",
            "parkAppointment": "园区预约",
            "record": "公路运输记录",
            "track": "公路运输轨迹",
            "inboundOrder": "入库订单",
            "dispatchBox": "运输订单箱码",
        }
        key = logical_parts[0] if logical_parts else ""
        subject = subjects.get(key, "")
        if not subject:
            return ""
        action_key = "/".join(logical_parts[1:])
        direct = {
            ("attachment", "downLoad"): "下载公路运输附件",
            ("attachment", "preview/url"): "获取公路运输附件预览地址",
            ("attachment", "preview"): "预览公路运输附件",
            ("attachment", "getContractAttachmentList"): "查询合同附件列表",
            ("attachment", "getDocumentList"): "查询单证附件列表",
            ("attachment", "deleteByList"): "按列表删除公路运输附件",
            ("attachment", "upload"): "上传公路运输附件",
            ("attachment", "uploadAndSave"): "上传并保存公路运输附件",
            ("cargo", "getCargoListByCarrierOrderNo"): "按承运商订单号查询公路运输货物列表",
            ("cargo", "getCargoListByDispatchOrderId"): "按调度订单 ID 查询公路运输货物列表",
            ("cargo", "getCargoListByDispatchOrderNo"): "按调度订单号查询公路运输货物列表",
            ("carrierOrder", "batchCreateCarrierOrder"): "批量创建公路承运商订单",
            ("carrierOrder", "batchDispatchOrder"): "批量调度公路承运商订单",
            ("carrierOrder", "changeCarrierOrderInfo"): "变更公路承运商订单信息",
            ("carrierOrder", "forceCloseOrder"): "强制关闭公路承运商订单",
            ("carrierOrder", "getCarrierInfoList"): "查询承运商信息列表",
            (
                "carrierOrder",
                "getDispatchContainerListByEntrustedNo",
            ): "按委托单号查询调度集装箱列表",
            ("carrierOrder", "getDispatchInfoList"): "查询调度信息列表",
            ("carrierOrder", "getFileIdByContractNo"): "按合同号查询文件 ID",
            ("carrierOrder", "listByEntrustedOrderNo"): "按委托订单号查询公路承运商订单",
            ("carrierOrder", "settlementCarrierPage"): "分页查询公路承运商结算订单",
            ("carrierOrder", "withdrawCarrierOrder"): "撤回公路承运商订单",
            ("carrierOrder", "getDispatchDetail"): "查询调度详情",
            ("dispatchOrder", "customPage"): "分页查询客户公路调度订单",
            ("dispatchOrder", "documentPage"): "分页查询公路调度订单单证",
            ("dispatchOrder", "getDispatchInfo"): "查询调度信息",
            ("dispatchOrder", "getDocumentById"): "按 ID 查询调度单证",
            ("dispatchOrder", "pageByCarrierNo"): "按承运商编号分页查询公路调度订单",
            ("dispatchOrder", "settlementDispatchPage"): "分页查询公路调度结算订单",
            ("dispatchOrder", "sign"): "签收公路调度订单",
            ("dispatchOrder", "getLoadInfo"): "查询装货信息",
            ("dispatchOrder", "getRedispatchDetail"): "查询重新调度详情",
            ("dispatchOrder", "getUnloadInfo"): "查询卸货信息",
            ("dispatchOrder", "load"): "装货",
            ("dispatchOrder", "modifyLoadInfo"): "修改装货信息",
            ("dispatchOrder", "modifyUnloadInfo"): "修改卸货信息",
            ("dispatchOrder", "redispatch"): "重新调度",
            ("dispatchOrder", "unload"): "卸货",
            ("parkAppointment", "parkList"): "查询园区列表",
            ("parkAppointment", "reappoint"): "重新预约园区",
            ("parkAppointment", "report"): "报到园区预约",
            ("record", "getListByDispatchOrderNo"): "按调度订单号查询公路运输记录",
            ("track", "carrierMapTrack"): "查询承运商公路地图轨迹",
            ("dispatchBox", "candidatePage"): "分页查询可关联箱码",
            ("dispatchBox", "list"): "查询运输订单已关联箱码",
        }
        if name := direct.get((key, action_key)):
            return name
        actions = {
            "page": "分页查询",
            "getById": "按 ID 查询",
            "deleteByIds": "批量删除",
            "saveOrUpdate": "保存",
            "edit": "修改",
        }
        action = actions.get(action_key)
        return f"{action}{subject}" if action else ""

    @staticmethod
    def _derive_remaining_api_name(path: str) -> str:
        """Path rules for the smaller, non-domain API groups."""
        parts = [part for part in str(path).split("/") if part and not part.startswith("{")]
        if not parts:
            return ""
        prefix = parts[0]
        ignored = {"admin", "portal", "api", "system"}
        logical = [part for part in parts[1:] if part not in ignored]
        joined = "/".join(logical)
        final_paths = {
            "api/sse/connect": "建立 SSE 连接",
            "api/sse/disconnect": "断开 SSE 连接",
            "api/sse/subscribe": "订阅 SSE 事件",
            "api/sse/unsubscribe": "取消订阅 SSE 事件",
            "inner/message/batchSend": "批量发送消息",
            "inner/message/send": "发送消息",
            "inner/message/group/robot/page": "分页查询群机器人",
            "inner/message/template/getByCode": "按编码查询消息模板",
            "inner/message/template/group/page": "分页查询消息模板分组",
            "inner/message/template/page": "分页查询消息模板",
            "sms/send": "发送短信",
            "test/emailSend": "发送测试邮件",
            "test/groupRobotSend": "发送测试群机器人消息",
            "test/sms/send": "发送测试短信",
            "test/smsSend": "发送测试短信",
            "zhiyun/railwayTransLocation": "上报铁路运输位置",
            "zhiyun/railwayTransportLocation": "查询铁路运输位置",
            "zhiyun/railwayTransTrace": "查询铁路运输轨迹",
            "admin/workbench/accountOverview": "查询账户概览",
            "admin/workbench/accountOverview/publicCompletedCarrierOrderCount": "查询公开已完成承运商订单数",
            "admin/workbench/shipperWorkbenchStatistics": "统计托运人工作台数据",
            "declaration-interface-api/admin/api/system/rolePermission/getMenuTreeByUserId": "查询用户菜单树",
            "internal/task-center/callback": "接收任务中心回调",
            "member-api/portal/port/noAuth/allPorts": "查询全部港口",
            "admin/driver/updateStatus": "更新司机状态",
            "declaration-api/admin/cargo/findOrderCargoQueryByCargoId": "按货物 ID 查询订单货物",
            "operation-api/admin/api/system/rolePermission/getMenuTreeByUserId": "查询用户菜单树",
            "order-api/dsly/common/order/carrierPage": "分页查询承运商订单",
            "order-api/dsly/common/order/shipperPage": "分页查询托运人订单",
        }
        full_path = "/".join(parts)
        if final_name := final_paths.get(full_path):
            return final_name

        groups: dict[str, dict[str, str]] = {
            "admin": {
                "attachment": "附件",
                "btDailyPlan": "日计划",
                "btDeparturePlan": "发车计划",
                "btDeparturePlanChangeRecord": "发车计划变更记录",
                "btDeparturePlanDailyPlan": "发车计划日计划",
                "btDeparturePlanStation": "发车计划站点",
                "btRoute": "线路",
                "btTrainOperationExceptionRecord": "列车运营异常记录",
                "btTrainOperationLog": "列车运营日志",
                "btTrainOperationMonitor": "列车运营监控",
                "btTrainOperationTracking": "列车运营跟踪",
                "btTrainPlanList": "列车计划",
                "btWaybill": "运单",
                "driver": "司机",
                "monthlyEntrusted": "月度委托",
                "monthlyEntrustedSupplement": "月度委托补充单",
            },
            "job-client-api": {
                "batch": "任务批次",
                "job": "定时任务",
                "log": "任务日志",
                "task": "任务",
                "job/warning/rule": "预警规则",
            },
            "message-api": {
                "email/sender": "邮件发送方",
                "email/sign": "邮件签名",
                "group/robot": "群机器人",
                "message/template": "消息模板",
                "message/templateGroup": "消息模板分组",
                "message/manual": "手工消息",
                "sms/sender": "短信发送方",
                "toolbox/file": "消息文件",
            },
            "external-interface-api": {
                "fee": "费用账单",
                "feeInfo": "费用信息",
                "rolePermission": "角色权限",
            },
        }
        subjects = groups.get(prefix, {})
        if not subjects:
            return ""
        resource = next(
            (
                key
                for key in sorted(subjects, key=len, reverse=True)
                if joined == key or joined.startswith(f"{key}/")
            ),
            "",
        )
        if not resource:
            return ""
        subject = subjects[resource]
        action_key = joined[len(resource) :].lstrip("/")
        direct = {
            ("admin", "attachment", "downLoad"): "下载附件",
            ("admin", "attachment", "upload"): "上传附件",
            ("admin", "btDailyPlan", "confirmBooking"): "确认订舱日计划",
            ("admin", "btDailyPlan", "listBoxes"): "查询日计划箱码列表",
            ("admin", "btDailyPlan", "saveBoxes"): "保存日计划箱码",
            ("admin", "btDeparturePlan", "exportLog"): "导出发车计划日志",
            ("admin", "btDeparturePlan", "execute"): "执行发车计划",
            ("admin", "btDeparturePlan", "publish"): "发布发车计划",
            ("admin", "btDeparturePlanDailyPlan", "availablePage"): "分页查询可用日计划",
            ("admin", "btDeparturePlanDailyPlan", "saveBatch"): "批量保存发车计划日计划",
            ("admin", "btDeparturePlanStation", "listByDeparturePlanId"): "按发车计划查询站点",
            ("admin", "btDeparturePlanStation", "saveActualTimeList"): "保存站点实际时间",
            ("admin", "btTrainOperationMonitor", "handleException"): "处理列车运营异常",
            ("admin", "btTrainOperationMonitor", "statistics"): "统计列车运营监控",
            ("admin", "btTrainOperationTracking", "markException"): "标记列车运营异常",
            ("admin", "btTrainOperationTracking", "recordExportLog"): "记录导出日志",
            ("admin", "btTrainOperationTracking", "recover"): "恢复列车运营跟踪",
            ("admin", "btTrainOperationTracking", "start"): "启动列车运营跟踪",
            ("admin", "btTrainPlanList", "execute"): "执行列车计划",
            ("admin", "btTrainPlanList", "exportLog"): "导出列车计划日志",
            ("admin", "btWaybill", "arrival"): "确认运单到达",
            ("admin", "driver", "approveAuth"): "审批司机认证",
            ("admin", "driver", "authHistory"): "查询司机认证历史",
            ("admin", "driver", "bindCarrier"): "绑定司机承运商",
            ("admin", "driver", "carrierOptions"): "查询承运商选项",
            ("admin", "driver", "carrierPage"): "分页查询承运商司机",
            ("admin", "driver", "clear/carrier"): "解绑司机承运商",
            ("admin", "driver", "disable"): "停用司机",
            ("admin", "driver", "enable"): "启用司机",
            ("admin", "driver", "mobile/current"): "查询当前司机",
            ("admin", "driver", "mobile/currentCarrier"): "查询当前司机承运商",
            ("admin", "driver", "rejectAuth"): "驳回司机认证",
            ("admin", "driver", "rejectAuthByRisk"): "因风险驳回司机认证",
            ("admin", "driver", "riskSnapshots"): "查询司机风险快照",
            ("admin", "driver", "startAuth"): "发起司机认证",
            ("admin", "driver", "updateAuthStatus"): "更新司机认证状态",
            ("admin", "monthlyEntrusted", "createReportPlan"): "创建月度委托报表计划",
            ("admin", "monthlyEntrustedSupplement", "confirm"): "确认月度委托补充单",
            ("admin", "monthlyEntrustedSupplement", "reject"): "驳回月度委托补充单",
            ("job-client-api", "job", "add"): "新增定时任务",
            ("job-client-api", "job", "exportData"): "导出定时任务数据",
            ("job-client-api", "job", "exportTemplate"): "导出定时任务模板",
            ("job-client-api", "job", "import"): "导入定时任务",
            ("job-client-api", "job", "nacos/services"): "查询 Nacos 服务",
            ("job-client-api", "job", "query"): "查询定时任务",
            ("job-client-api", "job", "triggerJob"): "触发定时任务",
            ("job-client-api", "job", "updateJobStatus"): "更新定时任务状态",
            ("job-client-api", "job/warning/rule", "batchDelete"): "批量删除预警规则",
            ("job-client-api", "job/warning/rule", "batchDisable"): "批量停用预警规则",
            ("job-client-api", "job/warning/rule", "batchEnable"): "批量启用预警规则",
            ("job-client-api", "job/warning/rule", "disable"): "停用预警规则",
            ("job-client-api", "job/warning/rule", "enable"): "启用预警规则",
            ("job-client-api", "job/warning/rule", "getByIds"): "按 ID 批量查询预警规则",
            ("message-api", "message/manual", "send"): "发送手工消息",
            ("message-api", "message/template", "appointReceiverRole"): "指定消息模板接收角色",
            (
                "message-api",
                "message/template",
                "appointReceiverUserList",
            ): "查询消息模板指定接收用户",
            (
                "message-api",
                "message/template",
                "appointReceiverUserPage",
            ): "分页查询消息模板指定接收用户",
            ("message-api", "toolbox/file", "download"): "下载消息文件",
            ("message-api", "toolbox/file", "preview"): "预览消息文件",
            ("message-api", "toolbox/file", "upload"): "上传消息文件",
            ("external-interface-api", "fee", "get"): "查询费用账单",
            ("external-interface-api", "fee", "save"): "保存费用账单",
            ("external-interface-api", "feeInfo", "findAll"): "查询全部费用信息",
            ("external-interface-api", "rolePermission", "getMenuTreeByUserId"): "查询用户菜单树",
        }
        if name := direct.get((prefix, resource, action_key)):
            return name
        actions = {
            "page": "分页查询",
            "getById": "按 ID 查询",
            "findById": "按 ID 查询",
            "deleteByIds": "批量删除",
            "save": "保存",
            "update": "更新",
            "change": "变更",
            "cancel": "取消",
            "complete": "完成",
            "dispatch": "调度",
            "remove": "删除",
            "findAll": "查询全部",
            "getByIds": "按 ID 批量查询",
            "delete": "删除",
            "get": "查询",
        }
        action = actions.get(action_key)
        return f"{action}{subject}" if action else ""

    @staticmethod
    def _derive_c12_portal_name(
        name: str,
        path: str,
        controller_name: str,
    ) -> str:
        """Rewrite only names that the original importer clearly generalized."""
        current = str(name).strip()
        broad_names = {
            "新增用户",
            "分页查询用户",
            "查询用户",
            "新增订单",
            "分页查询订单",
            "查询订单",
            "新增附件",
            "分页查询附件",
            "查询附件",
            "新增消息",
            "分页查询消息",
            "查询消息",
            "保存用户",
            "处理账户概览",
            "处理会员附件",
            "处理合同",
            "查询明细合同",
        }
        if (
            "相关" not in current
            and "controller" not in current.lower()
            and current not in broad_names
        ):
            return current

        subjects = {
            "AccountOverviewPortalController": "账户概览",
            "BtDailyPlanPortalController": "日计划",
            "BtWaybillPortalController": "运单",
            "ContractAdminController": "合同",
            "ContractPortalController": "合同",
            "RemoteContractPortalController": "合同",
            "EntrustedOrderComplainAdminController": "委托订单投诉",
            "EntrustedOrderComplainPortalController": "委托订单投诉",
            "EntrustedOrderEvaluationAdminController": "委托订单评价",
            "EntrustedOrderEvaluationPortalController": "委托订单评价",
            "EntrustedOrderPortalController": "委托订单",
            "InvoiceAdminController": "发票信息",
            "InvoicePortalController": "发票信息",
            "MemberAttachmentAdminController": "会员附件",
            "MemberAttachmentPortalController": "会员附件",
            "MessageRecipientAdminController": "消息接收人",
            "MessageRecipientPortalController": "消息接收人",
            "MonthlyEntrustedPortalController": "月度委托",
            "MonthlyEntrustedSupplementPortalController": "月度委托补充单",
            "OpenSysProxyController": "系统公共数据",
            "OperationEntryPortalController": "运营入口",
            "PortalConsortiumRegistrationController": "联合体报名",
            "PortalCustomerBillController": "客户账单",
            "PortalCustomerInvoiceController": "客户发票",
            "PortalCustomerOrderController": "客户订单",
            "PortalCustomerWorkbenchController": "客户工作台",
            "PortalObjectionComplaintController": "异议投诉",
            "PortalPriceRationalityController": "价格合理性分析",
            "PortalQualificationMatchController": "资质匹配",
            "PortalRemoteDecryptController": "远程解密授权",
            "PortalSupplierBillController": "供应商账单",
            "PortalSupplierInvoiceController": "供应商发票",
            "PortalSupplierOrderController": "供应商订单",
            "PortalSupplierWorkbenchController": "供应商工作台",
            "SelectTableController": "下拉数据",
            "ShipperLevelAdminController": "托运人等级",
            "ShipperLevelHistoryAdminController": "托运人等级历史",
            "UserInfoAdminController": "用户",
            "UserInfoPortalController": "用户",
            "RemoteUserInfoPortalController": "用户",
            "WmsInventoryPortalController": "WMS 库存",
            "WmsInventoryStocktakePortalController": "WMS 库存盘点",
            "WmsSelectTablePortalController": "WMS 下拉数据",
            "WmsStocktakeOrderPortalController": "WMS 盘点单",
            "WmsWarehousePortalController": "WMS 仓库",
            "门户公共文件Controller": "门户公共文件",
        }
        subject = subjects.get(str(controller_name).strip(), "")
        if not subject:
            cleaned_controller = str(controller_name).strip()
            if cleaned_controller.endswith("Controller"):
                cleaned_controller = cleaned_controller[:-10]
            if InterfaceForwardingService._contains_chinese(cleaned_controller):
                subject = cleaned_controller.removesuffix("接口").removesuffix("管理")
        if not subject:
            return current

        normalized_path = "/" + str(path).strip().lstrip("/")
        exact_names = {
            "/api/administrativeRegion/getChildRegionList": "查询下级行政区划",
            "/api/dictData/getDictDataAll": "查询全部字典数据",
            "/api/message/count": "统计未读消息",
            "/api/message/inapp/clear": "清空站内消息",
            "/api/message/inapp/markRead": "标记站内消息已读",
            "/api/message/inapp/markReadAll": "全部标记站内消息已读",
            "/api/message/inapp/markReadBatch": "批量标记站内消息已读",
            "/api/message/sendRecord/page": "分页查询消息发送记录",
            "/api/sys/file/batchDownload": "批量下载系统文件",
            "/api/sys/file/download/{id}": "下载系统文件",
            "/api/sys/file/preview/{id}": "预览系统文件",
            "/api/sys/taskcenter/download/{id}": "下载任务中心文件",
            "/api/sys/taskcenter/export": "导出任务中心数据",
            "/api/sys/taskcenter/page": "分页查询任务中心记录",
            "/api/sys/taskcenter/print/batch": "批量打印任务中心文件",
            "/member-api/admin/contract/configPage": "分页查询合同配置",
            "/member-api/admin/contract/getByIdItem": "查询合同明细",
            "/member-api/admin/contract/getRailwayValidCarrierList": "查询铁路有效承运商",
            "/member-api/admin/contract/getUserAllPage": "分页查询全部用户",
            "/member-api/admin/contract/pagePortDemands": "分页查询港口需求合同",
            "/member-api/admin/contract/selectCargoPage": "分页选择合同货物",
            "/member-api/admin/contract/syncContractInfo": "同步合同信息",
            "/member-api/admin/contract/validCarrierList": "查询合同有效承运商",
            "/member-api/admin/contract/validCarrierPage": "分页查询合同有效承运商",
            "/member-api/portal/contract/validCarrierList": "查询合同有效承运商",
            "/member-api/portal/contract/validCarrierPage": "分页查询合同有效承运商",
            "/member-api/portal/contract/getByIdItem": "查询合同明细",
            "/member-api/portal/contract/remote/validCarrierList": "查询承运商有效合同列表",
            "/member-api/portal/contract/remote/getByIdItem": "查询合同明细",
            "/member-api/admin/attachment/preview/url": "获取会员附件预览地址",
            "/member-api/admin/attachment/preview/{uuid}": "预览会员附件",
            "/member-api/admin/attachment/{uuid}": "获取会员附件地址",
            "/member-api/portal/attachment/preview/url": "获取会员附件预览地址",
            "/member-api/portal/attachment/preview/{uuid}": "预览会员附件",
            "/member-api/portal/attachment/{uuid}": "获取会员附件地址",
            "/member-api/portal/mtp/workbench/accountOverview/carrier": "查询承运商工作台账户概览",
            "/member-api/portal/mtp/workbench/accountOverview/shipper": "查询货主工作台账户概览",
            "/member-api/portal/operationEntry/list": "查询运营入口列表",
            "/member-api/portal/scts/customer/workbench/getOverview": "查询客户工作台概览",
            "/member-api/portal/scts/supplier/workbench/getOverview": "查询供应商工作台概览",
            "/member-api/portal/userInfo/getLoginUserInfo": "查询当前登录用户信息",
            "/member-api/portal/userInfo/getCompanyUsciAuthPreset": "查询企业认证预置信息",
            "/member-api/portal/userInfo/getMenuTreeByRoleCode": "按角色编码查询菜单树",
            "/member-api/portal/userInfo/personalCenterInfo": "查询个人中心信息",
            "/member-api/portal/userInfo/selectIdentity": "选择用户身份",
            "/member-api/portal/userInfo/updateEmail": "更新用户邮箱",
            "/member-api/portal/userInfo/updateMobile": "更新用户手机号",
            "/member-api/portal/userInfo/updatePortalUserInfo": "更新门户用户信息",
            "/member-api/portal/userInfo/updatePortalUserPassword": "更新门户用户密码",
            "/member-api/portal/userInfo/upgradeRole": "升级用户角色",
            "/member-api/portal/userInfo/userAuth": "提交用户认证",
            "/member-api/admin/userInfo/carrier/all": "查询全部承运商",
            "/member-api/admin/userInfo/carrierAll/page": "分页查询全部承运商",
            "/member-api/admin/userInfo/carrierAuth/page": "分页查询承运商认证",
            "/member-api/admin/userInfo/carrierManger/page": "分页查询承运商",
            "/member-api/admin/userInfo/carrierManger/page/export": "导出承运商",
            "/member-api/admin/userInfo/pageCustomsDeclarant": "分页查询报关员",
            "/member-api/admin/userInfo/shipperAuth/page": "分页查询托运人认证",
            "/member-api/admin/userInfo/shipperManger/page": "分页查询托运人",
            "/member-api/admin/userInfo/shipperManger/page/export": "导出托运人",
            "/member-api/admin/userInfo/shipper/page": "分页查询托运人",
            "/member-api/admin/userInfo/save": "保存用户信息",
            "/member-api/portal/wms/inventory/pageByOwner": "按货主分页查询 WMS 库存",
            "/member-api/portal/wms/inventory/pageBySku": "按 SKU 分页查询 WMS 库存",
            "/member-api/portal/wms/inventory/pageBySkuLoc": "按 SKU 库位分页查询 WMS 库存",
            "/api/file/material/checkDelete": "校验门户素材文件是否可删除",
            "/mtp/entrustedOrder/cargo/page": "分页查询委托订单货物",
            "/mtp/entrustedOrder/shipperPage": "分页查询委托订单托运人",
        }
        if exact := exact_names.get(normalized_path):
            return exact

        action_key = next(
            (
                part
                for part in reversed(normalized_path.split("/"))
                if part and not part.startswith("{")
            ),
            "",
        )
        action_names = {
            "page": "分页查询",
            "getPageList": "分页查询",
            "findById": "查询",
            "getById": "查询",
            "getByIdItem": "查询明细",
            "getByIds": "批量查询",
            "getByContractNo": "按合同号查询",
            "getValidContractByClientId": "按客户查询有效",
            "getValidContractByContractNos": "按合同号批量查询有效",
            "getValidShipperContractByClientId": "按客户查询有效托运人",
            "deleteByIds": "批量删除",
            "deleteById": "删除",
            "deleteUploadFile": "删除上传文件",
            "deleteByIdList": "批量删除",
            "cancelByIdList": "批量取消",
            "save": "保存",
            "saveOrEdit": "保存",
            "saveOrUpdate": "保存",
            "saveUploadFile": "保存上传文件",
            "submit": "提交",
            "submitById": "提交",
            "submitBidSubmission": "提交投标文件",
            "batchConfirm": "批量确认",
            "changeDisable": "停用",
            "changeEnable": "启用",
            "updateLevelStatus": "更新状态",
            "getByShipperId": "按托运人查询",
            "getNewestById": "查询最新",
            "createReportPlan": "创建报表计划",
            "confirm": "确认",
            "reject": "驳回",
            "cancel": "取消",
            "complete": "完成",
            "dispatch": "调度",
            "confirmBooking": "确认订舱",
            "listBoxes": "查询箱码列表",
            "saveBoxes": "保存箱码",
            "arrival": "确认到达",
            "getBidSubmissionDetail": "查询投标文件详情",
            "getLeaderSupplierProfile": "查询牵头供应商信息",
            "listProjectOptions": "查询项目选项",
            "matchMemberSupplier": "匹配联合体成员供应商",
            "generateReport": "生成分析报告",
            "getSuggestion": "查询分析建议",
            "statistics": "统计",
            "getDetail": "查询详情",
            "getFileForDownload": "获取下载文件",
            "listUploadFiles": "查询上传文件列表",
            "authorize": "授权远程解密",
            "getAuthDetail": "查询授权详情",
            "uploadInvoice": "上传发票",
            "ship": "发货",
            "shipInfo": "查询发货信息",
            "getByUserId": "按用户查询",
            "getPayerInvoiceInfoByUserId": "按用户查询付款方发票信息",
            "getAuthStatusByUserId": "查询用户认证状态",
            "getUserInfoById": "按 ID 查询用户信息",
            "getUserInfoByList": "按列表查询用户信息",
            "saveDriver": "保存司机",
            "syncEnterpriseUser": "同步企业用户",
            "register": "注册用户",
            "saveCustomsDeclarant": "保存报关员",
            "updateAgentStatus": "更新代理状态",
            "userDisable": "停用用户",
            "userEnable": "启用用户",
            "disable": "停用",
            "enable": "启用",
            "getAuthById": "查询认证信息",
            "getCarrierById": "查询承运商信息",
            "getCustomsDeclarantById": "查询报关员信息",
            "getShipperById": "查询托运人信息",
            "generaTask": "生成盘点任务",
            "getByTaskNo": "按任务编号查询",
        }
        action = action_names.get(action_key)
        if not action:
            lowered = action_key.lower()
            if "page" in lowered:
                action = "分页查询"
            elif lowered.startswith(("get", "find", "query", "list")):
                action = "查询"
            elif lowered.startswith(("delete", "remove")):
                action = "删除"
            elif lowered.startswith(("save", "create", "add")):
                action = "保存"
            elif lowered.startswith("update"):
                action = "更新"
            else:
                action = "处理"
        return f"{action}{subject}"

    @staticmethod
    def _derive_c12_data_name(name: str, path: str) -> str:
        """Return source-reviewed names for every endpoint exposed by c12-data."""
        normalized_path = "/" + str(path).strip().lstrip("/")
        exact_names = {
            "/data-api/portal/portal/userInfo/shipper/page": "分页查询门户托运人",
            "/data-api/portal/portal/userInfo/getUserInfoByList": "按用户 ID 批量查询门户用户",
            "/data-api/portal/portal/userInfo/getUserInfoById": "按用户 ID 查询门户用户",
            "/data-api/portal/portal/userInfo/getAuthStatusByUserId": "按用户 ID 查询认证状态",
            "/data-api/portal/portal/userInfo/carrierAll/page": "分页查询门户全部承运商",
            "/data-api/portal/portal/contract/validCarrierPage": "分页查询门户合同有效承运商",
            "/data-api/portal/portal/contract/validCarrierList": "查询门户合同有效承运商",
            "/data-api/portal/portal/contract/page": "分页查询门户合同",
            "/data-api/portal/portal/contract/getValidShipperContractByClientId": "按客户查询门户有效托运人合同",
            "/data-api/portal/portal/contract/getValidContractByClientId": "按客户查询门户有效合同",
            "/data-api/portal/portal/contract/getByIds": "按 ID 批量查询门户合同",
            "/data-api/portal/portal/contract/getByIdItem": "查询门户合同明细",
            "/data-api/portal/portal/contract/getByContractNo": "按合同号查询门户合同",
            "/data-api/portal/order/page": "分页查询公路派车单",
            "/data-api/portal/order/orderStatusStatistics": "统计公路派车单状态",
            "/data-api/portal/admin/warehouse/page": "分页查询仓储仓库",
            "/data-api/portal/admin/warehouse/list": "按条件查询仓储仓库列表",
            "/data-api/portal/admin/warehouse/inventory/page": "分页查询小程序库存仓库",
            "/data-api/portal/admin/warehouse/getByWarehouseCode": "按仓库代码查询仓库信息",
            "/data-api/portal/admin/userInfo/shipper/page": "分页查询后台托运人",
            "/data-api/portal/admin/userInfo/getUserInfoByList": "按用户 ID 批量查询后台用户",
            "/data-api/portal/admin/userInfo/getUserInfoById": "按用户 ID 查询后台用户",
            "/data-api/portal/admin/userInfo/existsMultimodalShipper": "判断是否存在多式联运托运人",
            "/data-api/portal/admin/userInfo/carrierAll/page": "分页查询后台全部承运商",
            "/data-api/portal/admin/userInfo/carrier/all": "查询后台全部承运商",
            "/data-api/portal/admin/park/list": "查询园区下拉列表",
            "/data-api/portal/admin/outboundBox/queryMtpShippingBindings": "查询多式联运发运单已绑定箱码",
            "/data-api/portal/admin/outboundBox/queryByBoxNos": "按箱码查询装箱数据",
            "/data-api/portal/admin/outboundBox/page": "分页查询装箱数据",
            "/data-api/portal/admin/invoice/getByUserId": "按用户 ID 查询发票信息",
            "/data-api/portal/admin/inventorySummary/page": "分页查询小程序库存",
            "/data-api/portal/admin/inventorySummary/listByWarehouseOwnerSku": "查询仓库货主商品库存列表",
            "/data-api/portal/admin/inventorySummary/listByWarehouseOwnerSkuAll": "按仓库、货主和商品编码查询全部库存",
            "/data-api/portal/admin/inventorySummary/detail": "查询小程序库存详情",
            "/data-api/portal/admin/contract/validCarrierPage": "分页查询后台合同有效承运商",
            "/data-api/portal/admin/contract/validCarrierList": "查询后台合同有效承运商",
            "/data-api/portal/admin/contract/page": "分页查询后台合同",
            "/data-api/portal/admin/contract/getValidShipperContractByClientId": "按客户查询后台有效托运人合同",
            "/data-api/portal/admin/contract/getValidContractByContractNos": "按合同号批量查询后台有效合同",
            "/data-api/portal/admin/contract/getValidContractByClientId": "按客户查询后台有效合同",
            "/data-api/portal/admin/contract/getRailwayValidCarrierList": "查询铁路有效承运商",
            "/data-api/portal/admin/contract/getByIds": "按 ID 批量查询后台合同",
            "/data-api/portal/admin/contract/getByIdItem": "查询后台合同明细",
            "/data-api/portal/admin/contract/getByContractNo": "按合同号查询后台合同",
            "/data-api/mtp/admin/goods/selectable/page": "分页查询可添加的 MTP 商品",
            "/data-api/mtp/admin/goods/selectable/getById": "按 ID 查询可添加的 MTP 商品",
            "/api/sse/unsubscribe": "取消订阅 SSE 消息",
            "/api/sse/subscribe": "订阅 SSE 消息",
            "/api/sse/disconnect": "断开 SSE 连接",
            "/api/sse/connect": "建立 SSE 连接",
        }
        return exact_names.get(normalized_path, str(name).strip())

    @staticmethod
    def _derive_source_controller_name(
        service_name: str,
        controller_name: str,
        path: str = "",
    ) -> str:
        """Resolve localized OpenAPI tags to the Java controller class name."""
        current = str(controller_name).strip()
        if service_name not in {"c12-mtp", "c12-portal", "c12-data"} or not current:
            return current
        if service_name == "c12-mtp" and current == "EntrustedOrderRelateAdminController":
            return "entrustedOrderRelateAdminController"
        if not InterfaceForwardingService._contains_chinese(current):
            return current

        tag = current.removesuffix("Controller")
        tag_to_controller = {
            "公路运输订单装箱明细": "HighwayDispatchBoxPortalController",
            "委托订单管理": "OrderEntrustedOrderPortalController",
            "运营端仓库管理": "WarehouseManagementAdminController",
            "运营端入库订单": "HighwayInboundOrderAdminController",
            "运营端出库订单": "OutboundOrderAdminController",
            "运营端商品档案": "ProductArchiveAdminController",
            "运营端委托需求": "OrderEntrustedAdminController",
            "运营端库存查询": "InventorySummaryAdminController",
            "门户端委托需求": "OrderEntrustedPortalController",
            "仓储仓库数据查询": "DataPortalWarehouseAdminController",
            "后台仓库信息": "DataPortalWarehouseInfoAdminController",
            "园区数据查询": "DataPortalParkAdminController",
            "装箱数据查询": "DataPortalOutboundBoxController",
            "供应链贸易发票小程序接口": "SctsInvoiceController",
            "供应链贸易合同": "SctsContractController",
            "供应链贸易小程序下拉数据查询接口": "SctsSelectTableController",
            "供应链贸易小程序工作台": "SctsWorkbenchController",
            "供应链贸易小程序数据看板菜单排序接口": "SctsMenuSortController",
            "供应链贸易库存小程序接口": "SctsInventoryController",
            "供应链贸易报表小程序接口": "SctsReportController",
            "供应链贸易物流跟踪小程序接口": "SctsLogisticsController",
            "供应链贸易订单小程序接口": "SctsOrderController",
            "供应链贸易账单小程序接口": "SctsBillController",
            "结算门户应付账单": "PayableBillSettlementPortalController",
            "结算门户应收账单": "ReceivableBillSettlementPortalController",
            "结算门户费用": "ExpenseSettlementPortalController",
            "结算门户费用修改日志": "ModifyLogSettlementPortalController",
            "结算门户销项发票": "SalesInvoiceSettlementPortalController",
            "结算门户预付": "PrepaymentSettlementPortalController",
            "门户WMS工作台": "WmsDashboardPortalController",
            "门户公共文件": "MemberFilePortalController",
            "门户内容标签管理": "PortalTagController",
            "门户内容统计": "PortalContentStatsController",
            "门户前台分类": "PortalFrontCategoryController",
            "门户前台文章": "PortalFrontArticleController",
            "门户前台页面资源": "PortalFrontPageController",
            "门户后台-新闻资讯-分类管理": "PortalCategoryController",
            "门户后台新闻资讯分类管理": "PortalCategoryController",
            "门户后台-驾驶舱管理": "CockpitDataController",
            "门户后台驾驶舱管理": "CockpitDataController",
            "门户小程序企业服务数据看板": "MiniEnterpriseDashboardController",
            "门户小程序企业认证": "MiniEnterpriseCertificationController",
            "门户小程序分类": "PortalMiniCategoryController",
            "门户小程序成交公示": "MiniPortalBidWinningController",
            "门户小程序投标文件查询": "MiniPortalExpertBidFileController",
            "门户小程序招标公告": "MiniPortalBidNoticeController",
            "门户小程序政务填报": "MiniGovernmentReportController",
            "门户小程序文件下载": "MiniPortalFileDownloadController",
            "门户小程序文章": "PortalMiniArticleController",
            "门户小程序澄清补遗": "MiniTenderClarificationAddendumController",
            "门户小程序用户": "UserInfoNoAuthMiniController",
            "门户小程序联合体报名": "MiniPortalConsortiumRegistrationController",
            "门户小程序评标评审": "MiniPortalExpertEvaluationController",
            "门户小程序评标邀请": "MiniPortalExpertInvitationController",
            "门户小程序资质匹配": "MiniPortalQualificationMatchController",
            "门户小程序资质更新": "MiniPortalSupplierQualificationController",
            "门户小程序页面资源": "PortalMiniPageController",
            "门户小程序项目审批": "MiniProjectApprovalController",
            "门户小程序项目文件查看": "MiniPortalProjectFileViewController",
            "门户小程序项目概览": "MiniProjectOverviewController",
            "门户广告图管理": "PortalAdController",
            "门户班列费用": "BtExpensePortalController",
            "门户移动端WMS工作台": "MobileWmsDashboardPortalController",
            "门户移动端库存盘点": "MobileWmsInventoryStocktakePortalController",
            "门户站点配置管理": "PortalSiteSettingController",
            "门户端-市场分析看板": "PortalMarketAnalysisController",
            "门户端市场分析看板": "PortalMarketAnalysisController",
            "门户端-投标人中标管理": "PortalBidWinningController",
            "门户端投标人中标管理": "PortalBidWinningController",
            "门户端-投标人保证金管理": "PortalDepositController",
            "门户端投标人保证金管理": "PortalDepositController",
            "门户端-投标人招标公告查看": "PortalBidNoticeController",
            "门户端投标人招标公告查看": "PortalBidNoticeController",
            "门户端-招投标大数据分析": "PortalBidAnalysisController",
            "门户端招投标大数据分析": "PortalBidAnalysisController",
            "门户端政务填报": "PortalGovernmentReportController",
            "门户资讯文章/帮助文章": "PortalArticleController",
            "门户轮播图管理": "PortalBannerController",
            "门户页脚导航管理": "PortalFooterNavController",
            "门户页面内容管理(关于我们/平台介绍)": "PortalPageContentController",
            "驾驶舱KPI指标数据管理": "CockpitKpiController",
            "驾驶舱事故率数据管理": "CockpitAccidentController",
            "驾驶舱企业货运排行数据管理": "CockpitEnterpriseRankController",
            "驾驶舱准点率汇总数据管理": "CockpitOntimeSummaryController",
            "驾驶舱准点率线路数据管理": "CockpitOntimeRouteController",
            "驾驶舱地图流向数据管理": "CockpitMapFlowController",
            "驾驶舱场站周转数据管理": "CockpitStationTurnoverController",
            "驾驶舱城市流向数据管理": "CockpitCityFlowController",
            "驾驶舱城市流向货类数据管理": "CockpitCityFlowCargoController",
            "驾驶舱拥堵时长数据管理": "CockpitCongestionController",
            "驾驶舱货物维度汇总数据管理": "CockpitCargoSummaryController",
            "驾驶舱货类占比数据管理": "CockpitCargoCategoryController",
            "驾驶舱运输时效线路数据管理": "CockpitTimelinessRouteController",
        }
        if tag == "运营端装箱管理":
            return (
                "OutboundBoxOrderAdminController"
                if str(path).startswith("/order-api/")
                else "OutboundBoxAdminController"
            )
        return tag_to_controller.get(tag, current)

    @staticmethod
    def _contains_chinese(value: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in value)

    @staticmethod
    def _tokenize_identifier(value: str) -> list[str]:
        if not value:
            return []
        step = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        step = step.replace("-", " ").replace("_", " ")
        result: list[str] = []
        for item in re.split(r"[^a-zA-Z0-9]+", step):
            cleaned = item
            if cleaned:
                result.append(cleaned.lower())
        return result

    @staticmethod
    def _lookup_cn_subject(token: str) -> str:
        subject_map = {
            "auth": "认证",
            "attachment": "附件",
            "carrier": "承运商",
            "company": "企业",
            "config": "配置",
            "configuration": "配置",
            "department": "部门",
            "dept": "部门",
            "dictionary": "字典",
            "driver": "司机",
            "file": "文件",
            "message": "消息",
            "notice": "通知",
            "order": "订单",
            "project": "项目",
            "report": "报表",
            "role": "角色",
            "route": "线路",
            "system": "系统",
            "task": "任务",
            "user": "用户",
            "vehicle": "车辆",
            "waybill": "运单",
            "cargo": "货物",
            "plan": "计划",
            "invoice": "发票",
            "line": "线路",
            "ship": "船舶",
            "batch": "批次",
            "portal": "门户",
            "product": "产品",
            "ticket": "票据",
            "pay": "支付",
            "payment": "支付",
            "settlement": "结算",
            "login": "登录",
            "account": "账号",
            "identity": "账号",
            "password": "密码",
            "token": "令牌",
            "log": "日志",
            "history": "历史",
            "version": "版本",
            "menu": "菜单",
            "module": "模块",
            "area": "区域",
        }
        candidate = token.lower().strip()
        if not candidate:
            return ""
        if candidate in subject_map:
            return subject_map[candidate]
        if candidate.endswith("ies"):
            alt = candidate[:-3] + "y"
            return subject_map.get(alt, "")
        if candidate.endswith("s"):
            alt = candidate[:-1]
            return subject_map.get(alt, "")
        if candidate.endswith("es"):
            if subject_map.get(candidate[:-2]):
                return subject_map[candidate[:-2]]
            if candidate.endswith("ses") and subject_map.get(candidate[:-3]):
                return subject_map[candidate[:-3]]
        return ""

    @staticmethod
    def _derive_subject_cn(
        name: str, operation_id: str, path: str, controller_description: str
    ) -> str:
        normalized_controller = str(controller_description).strip()
        if normalized_controller and InterfaceForwardingService._contains_chinese(
            normalized_controller
        ):
            for suffix in ("管理", "服务", "接口", "模块"):
                if normalized_controller.endswith(suffix):
                    normalized_controller = normalized_controller[: -len(suffix)]
                    break
            if normalized_controller:
                return normalized_controller

        # URL resources normally express the business object more directly than
        # an operation name (``batchCreateOrders`` starts with an action word).
        candidates = [path, name, operation_id]
        filtered = {"admin", "portal", "api", "inner", "message-api"}
        for candidate in candidates:
            for token in InterfaceForwardingService._tokenize_identifier(candidate):
                if token in filtered:
                    continue
                translated = InterfaceForwardingService._lookup_cn_subject(token)
                if translated:
                    return translated

        return ""

    @staticmethod
    def _derive_action_cn(
        method: str, summary: str, operation_id: str, path: str, name: str
    ) -> str:
        method_cn = {
            "get": "查询",
            "post": "新增",
            "put": "更新",
            "patch": "更新",
            "delete": "删除",
            "head": "查询",
            "options": "操作",
        }.get(method.lower(), "")

        action_map = {
            "find": "查询",
            "get": "查询",
            "page": "分页查询",
            "list": "查询",
            "query": "查询",
            "detail": "查看",
            "view": "查看",
            "save": "新增",
            "add": "新增",
            "create": "创建",
            "update": "更新",
            "edit": "修改",
            "modify": "修改",
            "delete": "删除",
            "remove": "删除",
            "submit": "提交",
            "confirm": "确认",
            "cancel": "取消",
            "sync": "同步",
            "import": "导入",
            "export": "导出",
            "upload": "上传",
            "download": "下载",
            "audit": "审核",
            "check": "校验",
            "count": "统计",
            "statistics": "统计",
            "search": "查询",
            "send": "发送",
            "dispatch": "调度",
            "complete": "完成",
            "revoke": "撤销",
            "approve": "审批",
        }

        for candidate in [summary, operation_id, path, name]:
            for token in InterfaceForwardingService._tokenize_identifier(candidate):
                action = action_map.get(token)
                if action:
                    return action

        path_tokens = [item for item in path.split("/") if item and not item.startswith("{")]
        for token in reversed(path_tokens):
            action = action_map.get(token)
            if action:
                return action

        return method_cn

    @staticmethod
    def _controller_metadata(spec: dict[str, Any], operation: dict[str, Any]) -> tuple[str, str]:
        tags = operation.get("tags")
        tag = str(tags[0]).strip() if isinstance(tags, list) and tags else ""
        if not tag:
            return "", ""

        tag_descriptions = {
            str(item.get("name") or "").strip(): str(item.get("description") or "").strip()
            for item in spec.get("tags", [])
            if isinstance(item, dict)
        }
        words = [word for word in tag.replace("_", "-").split("-") if word]
        controller_name = "".join(word[:1].upper() + word[1:] for word in words)
        if not controller_name.lower().endswith("controller"):
            controller_name += "Controller"

        description = tag_descriptions.get(tag, "")
        generic_descriptions = {tag, controller_name, tag.replace("-", " ")}
        if description.lower() in {item.lower() for item in generic_descriptions}:
            description = ""
        if not description:
            vocabulary = {
                "attachment": "附件",
                "auth": "认证",
                "carrier": "承运商",
                "company": "企业",
                "config": "配置",
                "department": "部门",
                "dept": "部门",
                "dictionary": "字典",
                "driver": "司机",
                "file": "文件",
                "log": "日志",
                "menu": "菜单",
                "message": "消息",
                "notice": "通知",
                "order": "订单",
                "project": "项目",
                "report": "报表",
                "role": "角色",
                "route": "线路",
                "system": "系统",
                "task": "任务",
                "user": "用户",
                "vehicle": "车辆",
            }
            subjects = [vocabulary[word.lower()] for word in words if word.lower() in vocabulary]
            description = (
                f"{'、'.join(dict.fromkeys(subjects))}管理" if subjects else f"{tag} 相关接口"
            )
        return controller_name, description

    def _connect(self):
        if not self._database_url:
            raise InterfaceForwardingError("控制面数据库尚未配置")
        return psycopg.connect(self._database_url, row_factory=dict_row)

    def overview(self, workspace_id: str, keyword: str = "") -> dict[str, Any]:
        like = f"%{keyword.strip()}%"
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT s.id, s.name, s.created_at, s.updated_at,
                       count(i.id)::int AS interface_count
                FROM interface_forwarding_services s
                LEFT JOIN interface_forwarding_interfaces i ON i.service_id = s.id
                WHERE s.workspace_id = %s
                GROUP BY s.id ORDER BY lower(s.name)
                """,
                (workspace_id,),
            )
            services = list(cursor.fetchall())
            cursor.execute(
                """
                SELECT i.id, i.service_id, i.name, i.path, i.method, i.description,
                       i.controller_name, i.controller_description,
                       i.operation_id, i.operation_kind, i.crud_type,
                       i.request_schema, i.response_schema, i.created_at, i.updated_at,
                       latest.last_requested_at,
                       profile.business_entity, profile.business_action,
                       profile.business_scenario, profile.aliases,
                       profile.positive_examples, profile.negative_examples,
                       profile.source AS intent_source,
                       profile.confidence AS intent_confidence,
                       COALESCE(effects.items, '[]'::jsonb) AS table_effects
                FROM interface_forwarding_interfaces i
                LEFT JOIN interface_forwarding_intent_profiles profile
                  ON profile.interface_id = i.id
                LEFT JOIN LATERAL (
                    SELECT logs.created_at AS last_requested_at
                    FROM interface_forwarding_logs logs
                    WHERE logs.interface_id = i.id
                    ORDER BY logs.created_at DESC
                    LIMIT 1
                ) latest ON TRUE
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'database_key', effect.database_key,
                            'schema_name', effect.schema_name,
                            'table_name', effect.table_name,
                            'effect_type', effect.effect_type,
                            'response_contribution', effect.response_contribution,
                            'source_file', effect.source_file,
                            'source_class', effect.source_class,
                            'source_method', effect.source_method,
                            'call_path', effect.call_path,
                            'evidence_type', effect.evidence_type,
                            'confidence', effect.confidence
                        ) ORDER BY effect.table_name, effect.effect_type
                    ) AS items
                    FROM interface_forwarding_table_effects effect
                    WHERE effect.interface_id = i.id
                ) effects ON TRUE
                WHERE i.workspace_id = %s
                  AND (%s = '' OR i.name ILIKE %s OR i.path ILIKE %s
                       OR i.description ILIKE %s
                       OR i.controller_name ILIKE %s OR i.controller_description ILIKE %s
                       OR profile.business_entity ILIKE %s
                       OR profile.business_action ILIKE %s
                       OR profile.business_scenario ILIKE %s
                       OR profile.aliases::text ILIKE %s
                       OR profile.positive_examples::text ILIKE %s)
                ORDER BY latest.last_requested_at DESC NULLS LAST,
                         lower(i.path), i.method
                """,
                (
                    workspace_id,
                    keyword.strip(),
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                ),
            )
            interfaces = list(cursor.fetchall())
            by_service: dict[str, list[dict[str, Any]]] = {}
            for item in interfaces:
                item["name"] = self._coalesce_interface_name(
                    str(item["name"]),
                    summary=str(item["description"] or ""),
                    path=str(item["path"]),
                    method=str(item["method"]),
                    controller_description=str(item["controller_description"] or ""),
                )
                by_service.setdefault(str(item["service_id"]), []).append(item)
            for service in services:
                service["interfaces"] = by_service.get(str(service["id"]), [])
            environments = self.list_environments(workspace_id, connection=connection)
        return {"workspace_id": workspace_id, "services": services, "environments": environments}

    def update_interface_semantics(
        self,
        interface_id: str,
        payload: InterfaceSemanticsWrite,
    ) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT workspace_id FROM interface_forwarding_interfaces WHERE id=%s FOR UPDATE",
                (interface_id,),
            )
            interface = cursor.fetchone()
            if not interface:
                raise InterfaceForwardingError("接口不存在")
            cursor.execute(
                "UPDATE interface_forwarding_interfaces SET crud_type=%s, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                (payload.crud_type, interface_id),
            )
            cursor.execute(
                """INSERT INTO interface_forwarding_intent_profiles
                       (interface_id, business_entity, business_action,
                        business_scenario, aliases, positive_examples,
                        negative_examples, source, confidence, manual_locked)
                   VALUES (%s, %s, %s, %s, %s, %s, %s,
                           'manual', 100, true)
                   ON CONFLICT (interface_id) DO UPDATE SET
                       business_entity=EXCLUDED.business_entity,
                       business_action=EXCLUDED.business_action,
                       business_scenario=EXCLUDED.business_scenario,
                       aliases=EXCLUDED.aliases,
                       positive_examples=EXCLUDED.positive_examples,
                       negative_examples=EXCLUDED.negative_examples,
                       source='manual', confidence=100, manual_locked=true,
                       updated_at=CURRENT_TIMESTAMP
                   RETURNING business_entity, business_action, business_scenario,
                             aliases, positive_examples, negative_examples,
                             source AS intent_source,
                             confidence AS intent_confidence""",
                (
                    interface_id,
                    payload.business_entity,
                    payload.business_action,
                    payload.business_scenario,
                    Jsonb(payload.aliases),
                    Jsonb(payload.positive_examples),
                    Jsonb(payload.negative_examples),
                ),
            )
            result = dict(cursor.fetchone())
        result.update({"id": interface_id, "crud_type": payload.crud_type})
        return result

    def import_spec(self, payload: InterfaceForwardingImport) -> dict[str, Any]:
        service_name = payload.service_name.strip()
        endpoints = self._parse_spec(payload.spec)
        if not endpoints:
            raise InterfaceForwardingError("Swagger/OpenAPI 文件中没有可导入的接口")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO interface_forwarding_services (id, workspace_id, name)
                VALUES (%s, %s, %s)
                ON CONFLICT (workspace_id, name) DO UPDATE
                SET updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                (str(uuid4()), payload.workspace_id, service_name),
            )
            service_id = str(cursor.fetchone()["id"])
            imported_count = 0
            for endpoint in endpoints:
                endpoint_id = str(uuid4())
                controller_name = self._derive_source_controller_name(
                    service_name,
                    endpoint["controller_name"],
                    endpoint["path"],
                )
                interface_name = self._coalesce_interface_name(
                    endpoint["name"],
                    operation_id=endpoint["operation_id"],
                    summary=endpoint["name"],
                    path=endpoint["path"],
                    method=endpoint["method"],
                    controller_description=endpoint["controller_description"],
                )
                if service_name == "c12-portal":
                    interface_name = self._derive_c12_portal_name(
                        interface_name,
                        endpoint["path"],
                        controller_name,
                    )
                elif service_name == "c12-data":
                    interface_name = self._derive_c12_data_name(
                        interface_name,
                        endpoint["path"],
                    )
                cursor.execute(
                    """
                    INSERT INTO interface_forwarding_interfaces
                        (id, workspace_id, service_id, name, path, method, description,
                         controller_name, controller_description, request_schema, response_schema,
                         operation_id, operation_kind, crud_type, request_contract)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (service_id, path, method) DO UPDATE SET
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        controller_name = EXCLUDED.controller_name,
                        controller_description = CASE
                            WHEN interface_forwarding_interfaces.controller_name
                                 = EXCLUDED.controller_name
                                 AND interface_forwarding_interfaces.controller_description <> ''
                            THEN interface_forwarding_interfaces.controller_description
                            ELSE EXCLUDED.controller_description
                        END,
                        request_schema = EXCLUDED.request_schema,
                        response_schema = EXCLUDED.response_schema,
                        operation_id = EXCLUDED.operation_id,
                        operation_kind = EXCLUDED.operation_kind,
                        crud_type = CASE
                            WHEN EXISTS (
                                SELECT 1
                                FROM interface_forwarding_intent_profiles profile
                                WHERE profile.interface_id = interface_forwarding_interfaces.id
                            ) THEN interface_forwarding_interfaces.crud_type
                            ELSE EXCLUDED.crud_type
                        END,
                        request_contract = EXCLUDED.request_contract,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (
                        endpoint_id,
                        payload.workspace_id,
                        service_id,
                        interface_name,
                        endpoint["path"],
                        endpoint["method"],
                        endpoint["description"],
                        controller_name,
                        endpoint["controller_description"],
                        Jsonb(endpoint["request_schema"]),
                        Jsonb(endpoint["response_schema"]),
                        endpoint["operation_id"],
                        endpoint["operation_kind"],
                        endpoint["crud_type"],
                        Jsonb(endpoint["request_contract"]),
                    ),
                )
                cursor.fetchone()
                imported_count += 1
        return {
            "service_id": service_id,
            "service_name": service_name,
            "imported_count": imported_count,
        }

    def rewrite_names(
        self,
        workspace_id: str,
        service_id: str | None = None,
        path_prefix: str | None = None,
    ) -> dict[str, Any]:
        query = """
            SELECT interface.id, interface.name, interface.description,
                   interface.path, interface.method, interface.controller_name,
                   interface.controller_description, service.name AS service_name
            FROM interface_forwarding_interfaces AS interface
            JOIN interface_forwarding_services AS service
              ON service.id = interface.service_id
            WHERE interface.workspace_id = %s
            """
        params: tuple[str, ...] = (workspace_id,)
        if service_id:
            query += " AND interface.service_id = %s"
            params = (workspace_id, service_id)
        if path_prefix:
            query += " AND interface.path LIKE %s"
            params = (*params, f"{path_prefix.rstrip('/')}%")

        updated = 0
        total = 0
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = list(cursor.fetchall())
            total = len(rows)
            for row in rows:
                normalized_controller_name = self._derive_source_controller_name(
                    str(row["service_name"]),
                    str(row["controller_name"] or ""),
                    str(row["path"]),
                )
                if str(row["service_name"]) == "c12-portal":
                    normalized_name = self._derive_c12_portal_name(
                        str(row["name"]),
                        str(row["path"]),
                        normalized_controller_name,
                    )
                elif str(row["service_name"]) == "c12-data":
                    normalized_name = self._derive_c12_data_name(
                        str(row["name"]),
                        str(row["path"]),
                    )
                else:
                    normalized_name = self._coalesce_interface_name(
                        str(row["name"]),
                        summary=str(row["description"] or ""),
                        path=str(row["path"]),
                        method=str(row["method"]),
                        controller_description=str(row["controller_description"] or ""),
                    )
                if normalized_name and (
                    normalized_name != str(row["name"])
                    or normalized_controller_name != str(row["controller_name"] or "")
                ):
                    cursor.execute(
                        """
                        UPDATE interface_forwarding_interfaces
                        SET name = %s,
                            controller_name = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (normalized_name, normalized_controller_name, row["id"]),
                    )
                    updated += 1

        return {
            "workspace_id": workspace_id,
            "service_id": service_id,
            "path_prefix": path_prefix,
            "total": total,
            "updated": updated,
        }

    @staticmethod
    def _parse_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
        paths = spec.get("paths")
        if not isinstance(paths, dict):
            return []

        def resolve(value: Any, seen: set[str] | None = None) -> Any:
            if not isinstance(value, dict) or "$ref" not in value:
                if isinstance(value, dict):
                    return {key: resolve(item, seen) for key, item in value.items()}
                if isinstance(value, list):
                    return [resolve(item, seen) for item in value]
                return value
            ref = str(value["$ref"])
            if not ref.startswith("#/") or ref in (seen or set()):
                return value
            current: Any = spec
            for part in ref[2:].split("/"):
                current = (
                    current.get(part.replace("~1", "/").replace("~0", "~"), {})
                    if isinstance(current, dict)
                    else {}
                )
            return resolve(current, (seen or set()) | {ref})

        endpoints: list[dict[str, Any]] = []
        methods = {"get", "post", "put", "patch", "delete", "head", "options"}
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method.lower() not in methods or not isinstance(operation, dict):
                    continue
                operation_id = str(operation.get("operationId") or "")
                controller_name, controller_description = (
                    InterfaceForwardingService._controller_metadata(spec, operation)
                )
                request_schema: Any = {}
                parameter_contract: dict[str, list[dict[str, Any]]] = {
                    "path": [],
                    "query": [],
                    "header": [],
                }
                combined_parameters: list[Any] = []
                path_parameters = path_item.get("parameters", [])
                if isinstance(path_parameters, list):
                    combined_parameters.extend(path_parameters)
                operation_parameters = operation.get("parameters", [])
                if isinstance(operation_parameters, list):
                    combined_parameters.extend(operation_parameters)
                for raw_parameter in combined_parameters:
                    parameter = resolve(raw_parameter)
                    if not isinstance(parameter, dict):
                        continue
                    location = str(parameter.get("in") or "")
                    if location not in parameter_contract:
                        continue
                    schema = resolve(parameter.get("schema", {}))
                    if not isinstance(schema, dict):
                        schema = {}
                    parameter_contract[location].append(
                        {
                            "name": str(parameter.get("name") or ""),
                            "required": bool(parameter.get("required")),
                            "description": str(parameter.get("description") or ""),
                            "schema": schema,
                            "example": parameter.get("example", schema.get("example")),
                        }
                    )
                request_body = operation.get("requestBody", {})
                if isinstance(request_body, dict):
                    content = request_body.get("content", {})
                    if isinstance(content, dict):
                        media = content.get("application/json") or next(iter(content.values()), {})
                        if isinstance(media, dict):
                            request_schema = media.get("schema", {})
                if not request_schema:
                    if isinstance(operation_parameters, list):
                        for parameter in operation_parameters:
                            if isinstance(parameter, dict) and parameter.get("in") == "body":
                                request_schema = parameter.get("schema", {})
                                break
                response_schema: Any = {}
                responses = operation.get("responses", {})
                if isinstance(responses, dict):
                    response = (
                        responses.get("200")
                        or responses.get("201")
                        or responses.get("default")
                        or next(iter(responses.values()), {})
                    )
                    if isinstance(response, dict):
                        content = response.get("content", {})
                        if isinstance(content, dict) and content:
                            media = content.get("application/json") or next(
                                iter(content.values()), {}
                            )
                            if isinstance(media, dict):
                                response_schema = media.get("schema", {})
                        response_schema = response_schema or response.get("schema", {})
                endpoints.append(
                    {
                        "name": str(
                            operation.get("summary") or operation_id or f"{method.upper()} {path}"
                        ),
                        "operation_id": operation_id,
                        "path": str(path),
                        "method": method.upper(),
                        "description": str(operation.get("description") or ""),
                        "controller_name": controller_name,
                        "controller_description": controller_description,
                        "request_schema": resolve(request_schema),
                        "response_schema": resolve(response_schema),
                        "operation_kind": InterfaceForwardingService._operation_kind(
                            method.upper(),
                            str(operation.get("summary") or operation_id or ""),
                        ),
                        "crud_type": InterfaceForwardingService._crud_type(
                            method.upper(),
                            str(operation.get("summary") or operation_id or ""),
                        ),
                        "request_contract": {
                            "path": InterfaceForwardingService._parameter_object_schema(
                                parameter_contract["path"]
                            ),
                            "query": InterfaceForwardingService._parameter_object_schema(
                                parameter_contract["query"]
                            ),
                            "header": InterfaceForwardingService._parameter_object_schema(
                                parameter_contract["header"]
                            ),
                            "body": resolve(request_schema),
                        },
                    }
                )
        return endpoints

    @staticmethod
    def _parameter_object_schema(parameters: list[dict[str, Any]]) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for parameter in parameters:
            name = str(parameter.get("name") or "").strip()
            if not name:
                continue
            schema = dict(parameter.get("schema") or {})
            if parameter.get("description") and "description" not in schema:
                schema["description"] = parameter["description"]
            if parameter.get("example") is not None and "example" not in schema:
                schema["example"] = parameter["example"]
            properties[name] = schema
            if parameter.get("required"):
                required.append(name)
        result: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            result["required"] = required
        return result

    @staticmethod
    def _operation_kind(method: str, name: str) -> str:
        if "取消订阅" in name:
            return "write"
        if re.match(r"^(删除|批量删除|取消|驳回|停用|禁用|撤销|清除)", name.strip()):
            return "destructive"
        if re.match(
            r"^(新增|保存|更新|修改|创建|上传|提交|确认|启用|同步|导入|发货|调度)",
            name.strip(),
        ):
            return "write"
        if method.upper() in {"GET", "HEAD", "OPTIONS"}:
            return "read"
        normalized = name.strip()
        if re.match(
            r"^(查询|分页查询|获取|统计|下载|预览|校验|检查|搜索|列出|按.+查询)",
            normalized,
        ):
            return "read"
        return "unknown"

    @staticmethod
    def _crud_type(method: str, name: str) -> str:
        normalized = name.strip()
        if re.match(
            r"^(删除|批量删除|清除|移除|作废|取消|撤销|注销)",
            normalized,
        ):
            return "delete"
        if re.match(
            r"^(查询|分页查询|获取|统计|下载|预览|校验|检查|搜索|列出|判断|"
            r"按.+(?:查询|获取))",
            normalized,
        ):
            return "read"
        if re.match(r"^(新增|创建|生成|上传|导入|发起|根据.+生成)", normalized):
            return "create"
        if re.match(
            r"^(更新|修改|保存|编辑|提交|确认|审核|审批|接受|拒绝|驳回|启用|停用|"
            r"同步|处理|关联|变更|撤回|签署|分配)",
            normalized,
        ):
            return "update"
        if method.upper() in {"GET", "HEAD", "OPTIONS"}:
            return "read"
        if method.upper() == "DELETE":
            return "delete"
        if method.upper() in {"PUT", "PATCH"}:
            return "update"
        return "unknown"

    def rename_service(self, service_id: str, name: str) -> dict[str, Any]:
        return self._update_returning(
            """UPDATE interface_forwarding_services
            SET name=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s
            RETURNING id, workspace_id, name, updated_at""",
            (name.strip(), service_id),
        )

    def delete_service(self, service_id: str) -> None:
        self._delete("interface_forwarding_services", service_id)

    def delete_interface(self, interface_id: str) -> None:
        self._delete("interface_forwarding_interfaces", interface_id)

    def list_environments(self, workspace_id: str, *, connection=None) -> list[dict[str, Any]]:
        owns = connection is None
        connection = connection or self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT workspace.workspace_id,
                              workspace.environment_key,
                              workspace.display_name,
                              workspace.sort_order,
                              workspace.is_default
                    FROM workspace_environments AS workspace
                    WHERE workspace.workspace_id=%s
                    ORDER BY workspace.sort_order, workspace.environment_key""",
                    (workspace_id,),
                )
                environments = list(cursor.fetchall())
                cursor.execute(
                    """SELECT address.id, address.workspace_id,
                              address.environment_key, address.service_id,
                              service.name AS service_name, address.name,
                              address.base_url, address.created_at, address.updated_at
                    FROM interface_forwarding_environments AS address
                    LEFT JOIN interface_forwarding_services AS service
                      ON service.id=address.service_id
                    WHERE address.workspace_id=%s
                    ORDER BY address.environment_key, lower(service.name),
                             lower(address.name), address.created_at""",
                    (workspace_id,),
                )
                addresses_by_key: dict[str, list[dict[str, Any]]] = {}
                for address in cursor.fetchall():
                    addresses_by_key.setdefault(str(address["environment_key"]), []).append(address)
                for environment in environments:
                    environment["addresses"] = addresses_by_key.get(
                        str(environment["environment_key"]), []
                    )
                return environments
        finally:
            if owns:
                connection.close()

    def create_environment(self, payload: InterfaceForwardingEnvironmentWrite) -> dict[str, Any]:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO interface_forwarding_environments (
                            id, workspace_id, environment_key, service_id, name, base_url
                        )
                        SELECT %s, workspace.workspace_id, workspace.environment_key,
                               service.id, %s, %s
                        FROM workspace_environments AS workspace
                        JOIN interface_forwarding_services AS service
                          ON service.workspace_id=workspace.workspace_id
                         AND service.id=%s
                        WHERE workspace.workspace_id=%s
                          AND workspace.environment_key=%s
                        RETURNING id, workspace_id, environment_key, service_id,
                                  name, base_url, created_at, updated_at""",
                    (
                        str(uuid4()),
                        payload.name.strip(),
                        payload.base_url,
                        payload.service_id,
                        payload.workspace_id,
                        payload.environment_key,
                    ),
                )
                row = cursor.fetchone()
                if not row:
                    raise InterfaceForwardingError("当前环境或接口服务不存在")
                cursor.execute(
                    "SELECT name FROM interface_forwarding_services WHERE id=%s",
                    (row["service_id"],),
                )
                row["service_name"] = cursor.fetchone()["name"]
                return row
        except psycopg.errors.UniqueViolation as exc:
            raise InterfaceForwardingError("这个环境下已存在相同的地址名称") from exc

    def update_environment(
        self, environment_id: str, payload: InterfaceForwardingEnvironmentWrite
    ) -> dict[str, Any]:
        try:
            return self._update_returning(
                """UPDATE interface_forwarding_environments AS forwarding
                SET service_id=service.id, name=%s, base_url=%s,
                    updated_at=CURRENT_TIMESTAMP
                FROM workspace_environments AS workspace
                JOIN interface_forwarding_services AS service
                  ON service.workspace_id=workspace.workspace_id
                 AND service.id=%s
                WHERE forwarding.id=%s
                  AND forwarding.workspace_id=%s
                  AND workspace.workspace_id=forwarding.workspace_id
                  AND workspace.environment_key=%s
                  AND forwarding.environment_key=workspace.environment_key
                RETURNING forwarding.id, forwarding.workspace_id,
                          forwarding.environment_key, forwarding.service_id,
                          service.name AS service_name, forwarding.name,
                          forwarding.base_url, forwarding.created_at,
                          forwarding.updated_at""",
                (
                    payload.name.strip(),
                    payload.base_url,
                    payload.service_id,
                    environment_id,
                    payload.workspace_id,
                    payload.environment_key,
                ),
            )
        except InterfaceForwardingError as exc:
            if str(exc) == "同一工作空间内名称或接口已存在":
                raise InterfaceForwardingError("这个环境下已存在相同的地址名称") from exc
            raise

    def delete_environment(self, environment_id: str) -> None:
        self._delete("interface_forwarding_environments", environment_id)

    def list_identities(
        self, workspace_id: str, environment_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT i.id, i.workspace_id, i.environment_id, i.login_account,
                       i.role_name, i.request_header, i.created_at, i.updated_at,
                       e.environment_key, e.name AS environment_name
                FROM interface_forwarding_identities i
                JOIN interface_forwarding_environments e ON e.id=i.environment_id
                WHERE i.workspace_id=%s AND (%s::text IS NULL OR e.id=%s)
                ORDER BY lower(i.login_account)
                """,
                (workspace_id, environment_id, environment_id),
            )
            return list(cursor.fetchall())

    def create_identity(self, payload: InterfaceForwardingIdentityWrite) -> dict[str, Any]:
        return self._write_identity(str(uuid4()), payload, create=True)

    def update_identity(
        self, identity_id: str, payload: InterfaceForwardingIdentityWrite
    ) -> dict[str, Any]:
        return self._write_identity(identity_id, payload, create=False)

    def _write_identity(
        self, identity_id: str, payload: InterfaceForwardingIdentityWrite, *, create: bool
    ) -> dict[str, Any]:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """SELECT id, environment_key, name FROM interface_forwarding_environments
                    WHERE id=%s AND workspace_id=%s""",
                    (payload.environment_id, payload.workspace_id),
                )
                environment = cursor.fetchone()
                if not environment:
                    raise InterfaceForwardingError("转发地址不存在")
                if create:
                    cursor.execute(
                        """INSERT INTO interface_forwarding_identities (
                                id, workspace_id, environment_id, login_account,
                                role_name, request_header
                            ) VALUES (%s,%s,%s,%s,%s,%s)
                            RETURNING id, workspace_id, environment_id, login_account,
                                      role_name, request_header, created_at, updated_at""",
                        (
                            identity_id,
                            payload.workspace_id,
                            environment["id"],
                            payload.login_account.strip(),
                            payload.role_name.strip(),
                            payload.request_header,
                        ),
                    )
                else:
                    cursor.execute(
                        """UPDATE interface_forwarding_identities
                            SET environment_id=%s, login_account=%s, role_name=%s,
                                request_header=%s,
                                updated_at=CURRENT_TIMESTAMP
                            WHERE id=%s AND workspace_id=%s
                            RETURNING id, workspace_id, environment_id, login_account,
                                      role_name, request_header, created_at, updated_at""",
                        (
                            environment["id"],
                            payload.login_account.strip(),
                            payload.role_name.strip(),
                            payload.request_header,
                            identity_id,
                            payload.workspace_id,
                        ),
                    )
                row = cursor.fetchone()
                if not row:
                    raise InterfaceForwardingError("请求身份不存在")
                row["environment_key"] = environment["environment_key"]
                row["environment_name"] = environment["name"]
                return row
        except psycopg.errors.UniqueViolation as exc:
            raise InterfaceForwardingError("这个转发地址下已存在相同登录账号和角色") from exc

    def delete_identity(self, identity_id: str) -> None:
        self._delete("interface_forwarding_identities", identity_id)

    def interface_state(self, interface_id: str) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT id, workspace_id, service_id, name, path, method,
                          description, request_schema, response_schema
                   FROM interface_forwarding_interfaces WHERE id=%s""",
                (interface_id,),
            )
            interface = cursor.fetchone()
            if not interface:
                raise InterfaceForwardingError("接口不存在")
            cursor.execute(
                """SELECT environment_id, identity_id, request_body,
                          response_body, params.updated_at, environment.environment_key
                   FROM interface_forwarding_params AS params
                   LEFT JOIN interface_forwarding_environments AS environment
                     ON environment.id=params.environment_id
                   WHERE interface_id=%s""",
                (interface_id,),
            )
            last_params = cursor.fetchone()
        return {"interface": interface, "last_params": last_params}

    def logs(self, interface_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT id, environment_name, identity_name, identity_role,
                request_url, request_body,
                response_body, status_code, success, duration_ms,
                created_at
                FROM interface_forwarding_logs WHERE interface_id=%s
                ORDER BY created_at DESC LIMIT %s""",
                (interface_id, max(1, min(limit, 200))),
            )
            return list(cursor.fetchall())

    def record_external_log(
        self, interface_id: str, payload: InterfaceForwardingLogWrite
    ) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT id, workspace_id, service_id, path
                FROM interface_forwarding_interfaces WHERE id=%s""",
                (interface_id,),
            )
            interface = cursor.fetchone()
            if not interface:
                raise InterfaceForwardingError("接口不存在")
            cursor.execute(
                """SELECT forwarding.id, forwarding.service_id, forwarding.name,
                          forwarding.base_url,
                          workspace.display_name AS workspace_environment_name
                FROM interface_forwarding_environments AS forwarding
                JOIN workspace_environments AS workspace
                  ON workspace.workspace_id=forwarding.workspace_id
                 AND workspace.environment_key=forwarding.environment_key
                WHERE forwarding.workspace_id=%s AND forwarding.id=%s""",
                (interface["workspace_id"], payload.environment_id),
            )
            environment = cursor.fetchone()
            if not environment:
                raise InterfaceForwardingError("转发地址不存在")
            if str(environment["service_id"] or "") != str(interface["service_id"]):
                raise InterfaceForwardingError("转发地址未映射到当前接口服务")
            cursor.execute(
                """SELECT id, login_account, role_name
                FROM interface_forwarding_identities
                WHERE id=%s AND environment_id=%s""",
                (payload.identity_id, environment["id"]),
            )
            identity = cursor.fetchone()
            if not identity:
                raise InterfaceForwardingError("请求身份不存在或不属于当前环境")
            request_url = urljoin(
                environment["base_url"].rstrip("/") + "/",
                interface["path"].lstrip("/"),
            )
            log_id = str(uuid4())
            cursor.execute(
                """INSERT INTO interface_forwarding_logs
                (id, workspace_id, interface_id, environment_name, identity_name,
                 identity_role, request_url, request_body, response_body, status_code,
                 success, duration_ms)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id, environment_name, identity_name, identity_role,
                          request_url, request_body, response_body, status_code,
                          success, duration_ms, created_at""",
                (
                    log_id,
                    interface["workspace_id"],
                    interface_id,
                    f"{environment['workspace_environment_name']} · {environment['name']}",
                    identity["login_account"],
                    identity["role_name"],
                    request_url,
                    payload.request_body,
                    payload.response_body,
                    payload.status_code,
                    payload.success,
                    payload.duration_ms,
                ),
            )
            return cursor.fetchone()

    def execute(self, interface_id: str, payload: InterfaceForwardingExecute) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT id, workspace_id, service_id, path, method
                FROM interface_forwarding_interfaces WHERE id=%s""",
                (interface_id,),
            )
            interface = cursor.fetchone()
            if not interface:
                raise InterfaceForwardingError("接口不存在")
            cursor.execute(
                """SELECT forwarding.id, forwarding.service_id, forwarding.name,
                          forwarding.environment_key, forwarding.base_url,
                          workspace.display_name AS workspace_environment_name
                FROM interface_forwarding_environments AS forwarding
                JOIN workspace_environments AS workspace
                  ON workspace.workspace_id=forwarding.workspace_id
                 AND workspace.environment_key=forwarding.environment_key
                WHERE forwarding.workspace_id=%s AND forwarding.id=%s""",
                (interface["workspace_id"], payload.environment_id),
            )
            environment = cursor.fetchone()
            if not environment:
                raise InterfaceForwardingError("转发地址不存在")
            if str(environment["service_id"] or "") != str(interface["service_id"]):
                raise InterfaceForwardingError("转发地址未映射到当前接口服务")
            identity = None
            if payload.identity_id:
                cursor.execute(
                    """SELECT id, login_account, role_name, request_header
                    FROM interface_forwarding_identities
                    WHERE id=%s AND environment_id=%s""",
                    (payload.identity_id, environment["id"]),
                )
                identity = cursor.fetchone()
                if not identity:
                    raise InterfaceForwardingError("请求身份不存在或不属于当前环境")

        headers: dict[str, str] = {"Accept": "application/json"}
        if identity and identity["request_header"].strip():
            raw_header = identity["request_header"].strip()
            try:
                parsed = json.loads(raw_header)
                if not isinstance(parsed, dict):
                    raise ValueError
                headers.update({str(key): str(value) for key, value in parsed.items()})
            except (json.JSONDecodeError, ValueError):
                headers["Authorization"] = raw_header
        body: Any = None
        if payload.request_body.strip():
            try:
                body = json.loads(payload.request_body)
            except json.JSONDecodeError as exc:
                raise InterfaceForwardingError("请求参数不是合法 JSON") from exc
        url = urljoin(environment["base_url"].rstrip("/") + "/", interface["path"].lstrip("/"))
        started = time.perf_counter()
        status_code: int | None = None
        success = False
        response_body = ""
        response_headers: dict[str, str] = {}
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                response = client.request(
                    interface["method"],
                    url,
                    headers=headers,
                    json=body if interface["method"] not in {"GET", "HEAD"} else None,
                    params=body
                    if interface["method"] in {"GET", "HEAD"} and isinstance(body, dict)
                    else None,
                )
            status_code = response.status_code
            success = response.is_success
            response_headers = dict(response.headers)
            try:
                response_body = json.dumps(response.json(), ensure_ascii=False, indent=2)
            except ValueError:
                response_body = response.text
        except httpx.HTTPError as exc:
            response_body = f"请求失败：{exc.__class__.__name__}: {exc}"
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO interface_forwarding_params
                (interface_id, environment_id, identity_id, request_body, response_body, updated_at)
                VALUES (%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
                ON CONFLICT (interface_id) DO UPDATE SET environment_id=EXCLUDED.environment_id,
                identity_id=EXCLUDED.identity_id, request_body=EXCLUDED.request_body,
                response_body=EXCLUDED.response_body, updated_at=CURRENT_TIMESTAMP""",
                (
                    interface_id,
                    environment["id"],
                    payload.identity_id,
                    payload.request_body,
                    response_body,
                ),
            )
            cursor.execute(
                """INSERT INTO interface_forwarding_logs
                (id, workspace_id, interface_id, environment_name, identity_name,
                 identity_role, request_url, request_body, response_body, status_code,
                 success, duration_ms)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(uuid4()),
                    interface["workspace_id"],
                    interface_id,
                    f"{environment['workspace_environment_name']} · {environment['name']}",
                    identity["login_account"] if identity else None,
                    identity["role_name"] if identity else "",
                    url,
                    payload.request_body,
                    response_body,
                    status_code,
                    success,
                    duration_ms,
                ),
            )
        return {
            "success": success,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "response_body": response_body,
            "response_headers": response_headers,
        }

    def _update_returning(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                if not row:
                    raise InterfaceForwardingError("记录不存在")
                return row
        except psycopg.errors.UniqueViolation as exc:
            raise InterfaceForwardingError("同一工作空间内名称或接口已存在") from exc

    def _delete(self, table: str, record_id: str) -> None:
        allowed = {
            "interface_forwarding_services",
            "interface_forwarding_interfaces",
            "interface_forwarding_environments",
            "interface_forwarding_identities",
        }
        if table not in allowed:
            raise InterfaceForwardingError("不支持的删除目标")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {table} WHERE id=%s", (record_id,))
            if cursor.rowcount == 0:
                raise InterfaceForwardingError("记录不存在")
