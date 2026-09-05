from __future__ import annotations

from pathlib import Path

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


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    java = "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz/src/main/java/com/example/"
    sql = (
        "backend/c12-mtp/c12-mtp-order-service/c12-mtp-order-biz/src/main/resources/sql-ext/order/"
    )
    _write(
        tmp_path,
        java + "Demo.java",
        '@Table(name = "cs_dsly_order_demo") public class Demo {}',
    )
    _write(
        tmp_path,
        java + "DemoController.java",
        """
        public class DemoController {
            private DemoService demoService;
            @PostMapping("/page")
            public Object page(Object condition) {
                return demoService.page(condition);
            }
            @PostMapping("/save")
            public Object save(Object item) {
                demoService.save(item);
                return null;
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "DemoService.java",
        """
        public class DemoService extends DemoBasicService {
            public Object page(Object condition) { return dao.page(condition); }
            public void save(Object item) { dao.update(item); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "DemoBasicService.java",
        """
        public class DemoBasicService
            extends ModuleBaseServiceSupport<DemoDao, Demo, Long> {}
        """,
    )
    _write(
        tmp_path,
        java + "DemoDao.java",
        """
        public class DemoDao extends ModuleBaseDaoSupport<Demo, Long> {
            public Object page(Object condition) {
                return sqlExecutor.page(Object.class, OrderSqlId.DEMO_PAGE, condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "OrderSqlId.java",
        'public class OrderSqlId { public static final String DEMO_PAGE = "demo_page"; }',
    )
    _write(
        tmp_path,
        sql + "demo_page.sql",
        """
        select d.id, e.name
        from cs_dsly_order_demo d
        left join cs_dsly_order_extra e on e.demo_id=d.id
        """,
    )
    return tmp_path


def test_analyzer_resolves_controller_service_dao_and_sql_tables(tmp_path: Path) -> None:
    analyzer = OrderApiSourceAnalyzer(_fixture(tmp_path))

    result = analyzer.analyze(
        controller_name="DemoController",
        path="/order-api/admin/demo/page",
        method="POST",
        interface_name="分页查询演示订单",
    )

    assert result.controller_method == "page"
    assert result.crud_type == "read"
    assert [(effect.table_name, effect.effect_type) for effect in result.effects] == [
        ("cs_dsly_order_demo", "select"),
        ("cs_dsly_order_extra", "select"),
    ]
    assert all(effect.response_contribution == "returned" for effect in result.effects)
    assert all(effect.sql_statement_id == "demo_page" for effect in result.effects)
    assert "分页查询演示订单" in result.aliases
    assert "演示订单列表" in result.aliases


def test_analyzer_classifies_write_and_uses_primary_model_table(tmp_path: Path) -> None:
    analyzer = OrderApiSourceAnalyzer(_fixture(tmp_path))

    result = analyzer.analyze(
        controller_name="DemoController",
        path="/order-api/admin/demo/save",
        method="POST",
        interface_name="保存演示订单",
    )

    assert result.controller_method == "save"
    assert result.crud_type == "update"
    assert [(effect.table_name, effect.effect_type) for effect in result.effects] == [
        ("cs_dsly_order_demo", "update")
    ]


def test_analyzer_does_not_invent_tables_for_missing_controller(tmp_path: Path) -> None:
    analyzer = OrderApiSourceAnalyzer(_fixture(tmp_path))

    result = analyzer.analyze(
        controller_name="RemoteOnlyController",
        path="/order-api/admin/remote/page",
        method="POST",
        interface_name="分页查询远程数据",
    )

    assert result.controller_found is False
    assert result.controller_method == ""
    assert result.crud_type == "read"
    assert result.effects == ()


def test_line_analyzer_uses_line_module_and_line_sql_ids(tmp_path: Path) -> None:
    java = "backend/c12-mtp/c12-mtp-line-service/c12-mtp-line-biz/src/main/java/com/example/"
    sql = (
        "backend/c12-mtp/c12-mtp-line-service/c12-mtp-line-biz/"
        "src/main/resources/sql-ext/line/"
    )
    _write(
        tmp_path,
        java + "Route.java",
        '@Table(name = "cs_dsly_line_route") public class Route {}',
    )
    _write(
        tmp_path,
        java + "RouteAdminController.java",
        """
        public class RouteAdminController {
            private RouteService routeService;
            @PostMapping("/page")
            public Object page(Object condition) { return routeService.page(condition); }
            @PostMapping({"/getTemplateFileUrl", "/getTempleFileUrl"})
            public Object getTemplateFileUrl() { return null; }
            @PostMapping("/checkRelevanceDelete/{ids}")
            public Object checkRelevanceDelete(Object ids) { return checkRelevance(ids); }
            private Object checkRelevance(Object ids) { return routeService.check(ids); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "RouteService.java",
        """
        public class RouteService extends RouteBasicService {
            public Object page(Object condition) { return dao.page(condition); }
            public Object check(Object ids) { return dao.find(ids); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "RouteBasicService.java",
        """
        public class RouteBasicService
            extends ModuleBaseServiceSupport<RouteDao, Route, Long> {}
        """,
    )
    _write(
        tmp_path,
        java + "RouteDao.java",
        """
        public class RouteDao extends ModuleBaseDaoSupport<Route, Long> {
            public Object page(Object condition) {
                return sqlExecutor.page(Object.class, LineSqlId.ROUTE_PAGE, condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "LineSqlId.java",
        'public class LineSqlId { public static final String ROUTE_PAGE = "route_page"; }',
    )
    _write(
        tmp_path,
        sql + "route_page.sql",
        "select * from cs_dsly_line_route",
    )

    result = LineApiSourceAnalyzer(tmp_path).analyze(
        controller_name="RouteAdminController",
        path="/line-api/admin/route/page",
        method="POST",
        interface_name="分页查询线路",
    )

    assert result.controller_method == "page"
    assert result.business_entity == "线路"
    assert result.crud_type == "read"
    assert [(effect.table_name, effect.effect_type) for effect in result.effects] == [
        ("cs_dsly_line_route", "select")
    ]
    assert result.effects[0].sql_statement_id == "route_page"

    alias_result = LineApiSourceAnalyzer(tmp_path).analyze(
        controller_name="RouteAdminController",
        path="/line-api/admin/route/getTempleFileUrl",
        method="POST",
        interface_name="获取线路模板文件地址",
    )
    assert alias_result.controller_method == "getTemplateFileUrl"

    helper_result = LineApiSourceAnalyzer(tmp_path).analyze(
        controller_name="RouteAdminController",
        path="/line-api/admin/route/checkRelevanceDelete/{ids}",
        method="POST",
        interface_name="检查线路删除关联",
    )
    assert helper_result.controller_method == "checkRelevanceDelete"
    assert [(effect.table_name, effect.effect_type) for effect in helper_result.effects] == [
        ("cs_dsly_line_route", "select")
    ]


def test_basic_analyzer_uses_basic_module_and_basic_sql_ids(tmp_path: Path) -> None:
    java = "backend/c12-mtp/c12-mtp-basic-service/c12-mtp-basic-biz/src/main/java/com/example/"
    sql = (
        "backend/c12-mtp/c12-mtp-basic-service/c12-mtp-basic-biz/"
        "src/main/resources/sql-ext/cargo/"
    )
    _write(
        tmp_path,
        java + "Cargo.java",
        '@Table(name = "cs_dsly_basic_cargo") public class Cargo {}',
    )
    _write(
        tmp_path,
        java + "CargoAdminController.java",
        """
        public class CargoAdminController {
            private CargoService cargoService;
            @PostMapping("/page")
            public Object page(Object condition) { return cargoService.page(condition); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "CargoService.java",
        """
        public class CargoService extends CargoBasicService {
            public Object page(Object condition) { return dao.page(condition); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "CargoBasicService.java",
        """
        public class CargoBasicService
            extends ModuleBaseServiceSupport<CargoDao, Cargo, Long> {}
        """,
    )
    _write(
        tmp_path,
        java + "CargoDao.java",
        """
        public class CargoDao extends ModuleBaseDaoSupport<Cargo, Long> {
            public Object page(Object condition) {
                return sqlExecutor.page(Object.class, BasicSqlId.CARGO_PAGE, condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "BasicSqlId.java",
        'public class BasicSqlId { public static final String CARGO_PAGE = "cargo_page"; }',
    )
    _write(
        tmp_path,
        sql + "cargo_page.sql",
        "select * from cs_dsly_basic_cargo",
    )
    shipping_java = (
        "backend/c12-mtp/c12-mtp-shipping-service/c12-mtp-shipping-biz/"
        "src/main/java/com/example/"
    )
    shipping_sql = (
        "backend/c12-mtp/c12-mtp-shipping-service/c12-mtp-shipping-biz/"
        "src/main/resources/sql-ext/dispatch/"
    )
    _write(
        tmp_path,
        shipping_java + "ShippingManifest.java",
        '@Table(name = "cs_dsly_shipping_manifest") public class ShippingManifest {}',
    )
    _write(
        tmp_path,
        shipping_java + "ShippingDispatchManifestAdminController.java",
        """
        public class ShippingDispatchManifestAdminController {
            private ShippingManifestService manifestService;
            @PostMapping("/page")
            public Object page(Object condition) { return manifestService.page(condition); }
        }
        """,
    )
    _write(
        tmp_path,
        shipping_java + "ShippingManifestService.java",
        """
        public class ShippingManifestService extends ShippingManifestBasicService {
            public Object page(Object condition) { return dao.page(condition); }
        }
        """,
    )
    _write(
        tmp_path,
        shipping_java + "ShippingManifestBasicService.java",
        """
        public class ShippingManifestBasicService extends
            ModuleBaseServiceSupport<ShippingManifestDao, ShippingManifest, Long> {}
        """,
    )
    _write(
        tmp_path,
        shipping_java + "ShippingManifestDao.java",
        """
        public class ShippingManifestDao extends
            ModuleBaseDaoSupport<ShippingManifest, Long> {
            public Object page(Object condition) {
                return sqlExecutor.page(
                    Object.class, ShippingSqlId.MANIFEST_PAGE, condition
                );
            }
        }
        """,
    )
    _write(
        tmp_path,
        shipping_java + "ShippingSqlId.java",
        """
        public class ShippingSqlId {
            public static final String MANIFEST_PAGE = "manifest_page";
        }
        """,
    )
    _write(
        tmp_path,
        shipping_sql + "manifest_page.sql",
        "select * from cs_dsly_shipping_manifest",
    )

    result = BasicApiSourceAnalyzer(tmp_path).analyze(
        controller_name="CargoAdminController",
        path="/basic-api/admin/cargo/page",
        method="POST",
        interface_name="分页查询货物",
    )

    assert result.controller_method == "page"
    assert result.business_entity == "货物"
    assert result.crud_type == "read"
    assert [(effect.table_name, effect.effect_type) for effect in result.effects] == [
        ("cs_dsly_basic_cargo", "select")
    ]
    assert result.effects[0].sql_statement_id == "cargo_page"

    shipping_result = BasicApiSourceAnalyzer(tmp_path).analyze(
        controller_name="ShippingDispatchManifestAdminController",
        path="/basic-api/admin/dispatchManifest/page",
        method="POST",
        interface_name="分页查询水路舱单",
    )
    assert shipping_result.controller_method == "page"
    assert shipping_result.business_entity == "水路舱单"
    assert [(effect.table_name, effect.effect_type) for effect in shipping_result.effects] == [
        ("cs_dsly_shipping_manifest", "select")
    ]
    assert shipping_result.effects[0].sql_statement_id == "manifest_page"


def test_highway_analyzer_uses_highway_module_and_sql_ids(tmp_path: Path) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-highway-service/c12-mtp-highway-biz/"
        "src/main/java/com/example/"
    )
    sql = (
        "backend/c12-mtp/c12-mtp-highway-service/c12-mtp-highway-biz/"
        "src/main/resources/sql-ext/dispatch/"
    )
    _write(
        tmp_path,
        java + "DispatchOrder.java",
        '@Table(name = "cs_dsly_highway_dispatch_order") public class DispatchOrder {}',
    )
    _write(
        tmp_path,
        java + "HighwayDispatchOrderAdminController.java",
        """
        public class HighwayDispatchOrderAdminController {
            private HighwayDispatchOrderService dispatchOrderService;
            @PostMapping("/page")
            public Object page(Object condition) {
                return dispatchOrderService.page(condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "HighwayDispatchOrderService.java",
        """
        public class HighwayDispatchOrderService extends HighwayDispatchOrderBasicService {
            public Object page(Object condition) { return dao.page(condition); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "HighwayDispatchOrderBasicService.java",
        """
        public class HighwayDispatchOrderBasicService extends
            ModuleBaseServiceSupport<HighwayDispatchOrderDao, DispatchOrder, Long> {}
        """,
    )
    _write(
        tmp_path,
        java + "HighwayDispatchOrderDao.java",
        """
        public class HighwayDispatchOrderDao extends
            ModuleBaseDaoSupport<DispatchOrder, Long> {
            public Object page(Object condition) {
                return sqlExecutor.page(
                    Object.class, HighwaySqlId.DISPATCH_PAGE, condition
                );
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "HighwaySqlId.java",
        """
        public class HighwaySqlId {
            public static final String DISPATCH_PAGE = "dispatch_page";
        }
        """,
    )
    _write(
        tmp_path,
        sql + "dispatch_page.sql",
        "select * from cs_dsly_highway_dispatch_order",
    )

    result = HighwayApiSourceAnalyzer(tmp_path).analyze(
        controller_name="HighwayDispatchOrderAdminController",
        path="/highway-api/admin/dispatchOrder/page",
        method="POST",
        interface_name="分页查询公路运输订单",
    )

    assert result.controller_method == "page"
    assert result.business_entity == "公路运输订单"
    assert result.crud_type == "read"
    assert [(effect.table_name, effect.effect_type) for effect in result.effects] == [
        ("cs_dsly_highway_dispatch_order", "select")
    ]
    assert result.effects[0].sql_statement_id == "dispatch_page"


def test_railway_analyzer_uses_railway_module_and_sql_ids(tmp_path: Path) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-railway-service/c12-mtp-railway-biz/"
        "src/main/java/com/example/"
    )
    sql = (
        "backend/c12-mtp/c12-mtp-railway-service/c12-mtp-railway-biz/"
        "src/main/resources/sql-ext/dispatch/"
    )
    _write(
        tmp_path,
        java + "DailyPlan.java",
        '@Table(name = "cs_dsly_railway_daily_plan") public class DailyPlan {}',
    )
    _write(
        tmp_path,
        java + "RailwayDailyPlanAdminController.java",
        """
        public class RailwayDailyPlanAdminController {
            private RailwayDailyPlanService dailyPlanService;
            @PostMapping("/page")
            public Object page(Object condition) { return dailyPlanService.page(condition); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "RailwayDailyPlanService.java",
        """
        public class RailwayDailyPlanService extends RailwayDailyPlanBasicService {
            public Object page(Object condition) { return dao.page(condition); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "RailwayDailyPlanBasicService.java",
        """
        public class RailwayDailyPlanBasicService extends
            ModuleBaseServiceSupport<RailwayDailyPlanDao, DailyPlan, Long> {}
        """,
    )
    _write(
        tmp_path,
        java + "RailwayDailyPlanDao.java",
        """
        public class RailwayDailyPlanDao extends ModuleBaseDaoSupport<DailyPlan, Long> {
            public Object page(Object condition) {
                return sqlExecutor.page(Object.class, RailwaySqlId.PLAN_PAGE, condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "RailwaySqlId.java",
        """
        public class RailwaySqlId {
            public static final String PLAN_PAGE = "plan_page";
        }
        """,
    )
    _write(
        tmp_path,
        sql + "plan_page.sql",
        "select * from cs_dsly_railway_daily_plan",
    )

    result = RailwayApiSourceAnalyzer(tmp_path).analyze(
        controller_name="RailwayDailyPlanAdminController",
        path="/railway-api/admin/dailyPlan/page",
        method="POST",
        interface_name="分页查询铁路日发运计划",
    )

    assert result.controller_method == "page"
    assert result.business_entity == "铁路日发运计划"
    assert result.crud_type == "read"
    assert [(effect.table_name, effect.effect_type) for effect in result.effects] == [
        ("cs_dsly_railway_daily_plan", "select")
    ]
    assert result.effects[0].sql_statement_id == "plan_page"

    action_result = RailwayApiSourceAnalyzer(tmp_path).analyze(
        controller_name="RailwayDailyPlanAdminController",
        path="/railway-api/admin/dispatchOrder/load",
        method="POST",
        interface_name="装货",
    )
    assert action_result.crud_type == "update"


def test_shipping_analyzer_uses_shipping_module_and_sql_ids(tmp_path: Path) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-shipping-service/c12-mtp-shipping-biz/"
        "src/main/java/com/example/"
    )
    sql = (
        "backend/c12-mtp/c12-mtp-shipping-service/c12-mtp-shipping-biz/"
        "src/main/resources/sql-ext/dispatch/"
    )
    _write(
        tmp_path,
        java + "ShippingOrder.java",
        '@Table(name = "cs_dsly_shipping_dispatch_order") public class ShippingOrder {}',
    )
    _write(
        tmp_path,
        java + "ShippingDispatchOrderAdminController.java",
        """
        public class ShippingDispatchOrderAdminController {
            private ShippingDispatchOrderService dispatchOrderService;
            @PostMapping("/page")
            public Object page(Object condition) {
                return dispatchOrderService.page(condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "ShippingDispatchOrderService.java",
        """
        public class ShippingDispatchOrderService extends ShippingDispatchOrderBasicService {
            public Object page(Object condition) { return dao.page(condition); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "ShippingDispatchOrderBasicService.java",
        """
        public class ShippingDispatchOrderBasicService extends
            ModuleBaseServiceSupport<ShippingDispatchOrderDao, ShippingOrder, Long> {}
        """,
    )
    _write(
        tmp_path,
        java + "ShippingDispatchOrderDao.java",
        """
        public class ShippingDispatchOrderDao extends
            ModuleBaseDaoSupport<ShippingOrder, Long> {
            public Object page(Object condition) {
                return sqlExecutor.page(
                    Object.class, ShippingSqlId.DISPATCH_PAGE, condition
                );
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "ShippingSqlId.java",
        """
        public class ShippingSqlId {
            public static final String DISPATCH_PAGE = "shipping_dispatch_page";
        }
        """,
    )
    _write(
        tmp_path,
        sql + "shipping_dispatch_page.sql",
        "select * from cs_dsly_shipping_dispatch_order",
    )

    result = ShippingApiSourceAnalyzer(tmp_path).analyze(
        controller_name="ShippingDispatchOrderAdminController",
        path="/shipping-api/admin/dispatchOrder/page",
        method="POST",
        interface_name="分页查询水路运输订单",
    )

    assert result.controller_method == "page"
    assert result.business_entity == "水路运输订单"
    assert result.crud_type == "read"
    assert [(effect.table_name, effect.effect_type) for effect in result.effects] == [
        ("cs_dsly_shipping_dispatch_order", "select")
    ]
    assert result.effects[0].sql_statement_id == "shipping_dispatch_page"


def test_settlement_analyzer_uses_settlement_module_and_sql_ids(tmp_path: Path) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-settlement-service/c12-mtp-settlement-biz/"
        "src/main/java/com/example/"
    )
    sql = (
        "backend/c12-mtp/c12-mtp-settlement-service/c12-mtp-settlement-biz/"
        "src/main/resources/sql-ext/payment/"
    )
    _write(
        tmp_path,
        java + "PaymentApply.java",
        '@Table(name = "cs_dsly_settlement_payment_apply") public class PaymentApply {}',
    )
    _write(
        tmp_path,
        java + "PaymentApplyAdminController.java",
        """
        public class PaymentApplyAdminController {
            private PaymentApplyService paymentApplyService;
            @PostMapping("/page")
            public Object page(Object condition) { return paymentApplyService.page(condition); }
            @PostMapping("/batchInitiateReconciliation")
            public Object batchInitiateReconciliation(Object ids) {
                return paymentApplyService.batchInitiateReconciliation(ids);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "PaymentApplyService.java",
        """
        public class PaymentApplyService extends PaymentApplyBasicService {
            public Object page(Object condition) { return dao.page(condition); }
            public Object batchInitiateReconciliation(Object ids) {
                return batchUpdate(ids);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "PaymentApplyBasicService.java",
        """
        public class PaymentApplyBasicService extends
            ModuleBaseServiceSupport<PaymentApplyDao, PaymentApply, Long> {}
        """,
    )
    _write(
        tmp_path,
        java + "PaymentApplyDao.java",
        """
        public class PaymentApplyDao extends ModuleBaseDaoSupport<PaymentApply, Long> {
            public Object page(Object condition) {
                return sqlExecutor.page(
                    Object.class, SettlementSqlId.PAYMENT_PAGE, condition
                );
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "SettlementSqlId.java",
        """
        public class SettlementSqlId {
            public static final String PAYMENT_PAGE = "payment_page";
        }
        """,
    )
    _write(
        tmp_path,
        sql + "payment_page.sql",
        "select * from cs_dsly_settlement_payment_apply",
    )

    result = SettlementApiSourceAnalyzer(tmp_path).analyze(
        controller_name="PaymentApplyAdminController",
        path="/settlement-api/admin/paymentApply/page",
        method="POST",
        interface_name="分页查询付款申请",
    )

    assert result.controller_method == "page"
    assert result.business_entity == "付款申请"
    assert result.crud_type == "read"
    assert [(effect.table_name, effect.effect_type) for effect in result.effects] == [
        ("cs_dsly_settlement_payment_apply", "select")
    ]
    assert result.effects[0].sql_statement_id == "payment_page"

    reconciliation = SettlementApiSourceAnalyzer(tmp_path).analyze(
        controller_name="PaymentApplyAdminController",
        path="/settlement-api/admin/paymentApply/batchInitiateReconciliation",
        method="POST",
        interface_name="批量发起对账付款申请",
    )
    assert reconciliation.crud_type == "update"
    assert [(effect.table_name, effect.effect_type) for effect in reconciliation.effects] == [
        ("cs_dsly_settlement_payment_apply", "update")
    ]


def test_declaration_analyzer_uses_declaration_module_and_sql_ids(tmp_path: Path) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-declaration-service/c12-mtp-declaration-biz/"
        "src/main/java/com/example/"
    )
    sql = (
        "backend/c12-mtp/c12-mtp-declaration-service/c12-mtp-declaration-biz/"
        "src/main/resources/sql-ext/order/"
    )
    _write(
        tmp_path,
        java + "DeclarationOrder.java",
        '@Table(name = "cs_dsly_declaration_order") public class DeclarationOrder {}',
    )
    _write(
        tmp_path,
        java + "OrderAdminController.java",
        """
        public class OrderAdminController {
            private DeclarationOrderService orderService;
            @PostMapping("/page")
            public Object page(Object condition) {
                if (condition == null) { return null; }
                return orderService.page(condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "DeclarationOrderService.java",
        """
        public class DeclarationOrderService extends DeclarationOrderBasicService {
            public Object page(Object condition) { return dao.page(condition); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "DeclarationOrderBasicService.java",
        """
        public class DeclarationOrderBasicService extends
            ModuleBaseServiceSupport<DeclarationOrderDao, DeclarationOrder, Long> {}
        """,
    )
    _write(
        tmp_path,
        java + "DeclarationOrderDao.java",
        """
        public class DeclarationOrderDao extends
            ModuleBaseDaoSupport<DeclarationOrder, Long> {
            public Object page(Object condition) {
                return sqlExecutor.page(
                    Object.class, DeclarationSqlId.ORDER_PAGE, condition
                );
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "DeclarationSqlId.java",
        """
        public class DeclarationSqlId {
            public static final String ORDER_PAGE = "order_page";
        }
        """,
    )
    _write(
        tmp_path,
        sql + "order_page.sql",
        "select * from cs_dsly_declaration_order",
    )

    analyzer = DeclarationApiSourceAnalyzer(tmp_path)
    result = analyzer.analyze(
        controller_name="OrderAdminController",
        path="/declaration-api/admin/order/page",
        method="POST",
        interface_name="分页查询申报订单",
    )

    assert "if" not in analyzer.classes["OrderAdminController"].methods
    assert result.controller_method == "page"
    assert result.business_entity == "申报订单"
    assert result.crud_type == "read"
    assert [(effect.table_name, effect.effect_type) for effect in result.effects] == [
        ("cs_dsly_declaration_order", "select")
    ]
    assert result.effects[0].sql_statement_id == "order_page"


def test_operation_analyzer_supports_multiple_sql_id_classes(tmp_path: Path) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-operation-service/c12-mtp-operation-biz/"
        "src/main/java/com/example/"
    )
    sql = (
        "backend/c12-mtp/c12-mtp-operation-service/c12-mtp-operation-biz/"
        "src/main/resources/sql-ext/appointment/"
    )
    _write(
        tmp_path,
        java + "Appointment.java",
        '@Table(name = "cs_dsly_operation_appointment") public class Appointment {}',
    )
    _write(
        tmp_path,
        java + "AppointmentAdminController.java",
        """
        public class AppointmentAdminController {
            private AppointmentService appointmentService;
            @PostMapping("/page")
            public Object page(Object condition) {
                return appointmentService.page(condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "AppointmentService.java",
        """
        public class AppointmentService extends AppointmentBasicService {
            public Object page(Object condition) { return dao.page(condition); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "AppointmentBasicService.java",
        """
        public class AppointmentBasicService extends
            ModuleBaseServiceSupport<AppointmentDao, Appointment, Long> {}
        """,
    )
    _write(
        tmp_path,
        java + "AppointmentDao.java",
        """
        public class AppointmentDao extends ModuleBaseDaoSupport<Appointment, Long> {
            public Object page(Object condition) {
                return sqlExecutor.page(
                    Object.class, AppointmentSqlId.APPOINTMENT_PAGE, condition
                );
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "AppointmentSqlId.java",
        """
        public class AppointmentSqlId {
            public static final String APPOINTMENT_PAGE = "appointment_page";
        }
        """,
    )
    _write(
        tmp_path,
        java + "EntrustedSqlId.java",
        "public class EntrustedSqlId {}",
    )
    _write(
        tmp_path,
        sql + "appointment_page.sql",
        "select * from cs_dsly_operation_appointment",
    )

    analyzer = OperationApiSourceAnalyzer(tmp_path)
    result = analyzer.analyze(
        controller_name="AppointmentAdminController",
        path="/operation-api/admin/appointment/page",
        method="POST",
        interface_name="分页查询预约",
    )
    cancel_result = analyzer.analyze(
        controller_name="MissingController",
        path="/operation-api/admin/appointment/cancel",
        method="POST",
        interface_name="取消预约",
    )

    assert result.controller_method == "page"
    assert result.business_entity == "作业预约"
    assert result.crud_type == "read"
    assert [(effect.table_name, effect.effect_type) for effect in result.effects] == [
        ("cs_dsly_operation_appointment", "select")
    ]
    assert result.effects[0].sql_statement_id == "appointment_page"
    assert cancel_result.crud_type == "update"


def test_message_analyzer_corrects_bad_summary_from_controller_method(tmp_path: Path) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-message-service/c12-mtp-message-biz/"
        "src/main/java/com/example/"
    )
    sql = (
        "backend/c12-mtp/c12-mtp-message-service/c12-mtp-message-biz/"
        "src/main/resources/sql-ext/template/"
    )
    _write(
        tmp_path,
        java + "MessageTemplate.java",
        '@Table(name = "cs_message_template") public class MessageTemplate {}',
    )
    _write(
        tmp_path,
        java + "MessageTemplateController.java",
        """
        public class MessageTemplateController {
            private MessageTemplateService templateService;
            @PostMapping("/page")
            public Object page(Object condition) { return templateService.page(condition); }
            @PostMapping("/appointReceiverRole")
            public Object appointReceiverRole(Object condition) {
                return templateService.appointReceiverRole(condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "MessageRolePermissionController.java",
        """
        public class MessageRolePermissionController {
            private RemoteRolePermissionService remoteRolePermissionService;
            @PostMapping("/getMenuTreeByUserId")
            public Object getMenuTreeByUserId() {
                return remoteRolePermissionService.getMenuTreeByCondition();
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "MessageTemplateService.java",
        """
        public class MessageTemplateService extends MessageTemplateBasicService {
            public Object page(Object condition) { return dao.page(condition); }
            public Object appointReceiverRole(Object condition) {
                return remoteRoleService.list(condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "MessageTemplateBasicService.java",
        """
        public class MessageTemplateBasicService extends
            ModuleBaseServiceSupport<MessageTemplateDao, MessageTemplate, Long> {}
        """,
    )
    _write(
        tmp_path,
        java + "MessageTemplateDao.java",
        """
        public class MessageTemplateDao extends ModuleBaseDaoSupport<MessageTemplate, Long> {
            public Object page(Object condition) {
                return sqlExecutor.page(
                    Object.class, MessageSqlId.TEMPLATE_PAGE, condition
                );
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "MessageSqlId.java",
        """
        public class MessageSqlId {
            public static final String TEMPLATE_PAGE = "template_page";
        }
        """,
    )
    _write(
        tmp_path,
        sql + "template_page.sql",
        "select * from cs_message_template",
    )

    analyzer = MessageApiSourceAnalyzer(tmp_path)
    page_result = analyzer.analyze(
        controller_name="MessageTemplateController",
        path="/message-api/message/template/page",
        method="POST",
        interface_name="分页查询消息模板",
    )
    menu_result = analyzer.analyze(
        controller_name="MessageRolePermissionController",
        path="/message-api/admin/api/system/rolePermission/getMenuTreeByUserId",
        method="POST",
        interface_name="新增消息、角色",
    )
    role_result = analyzer.analyze(
        controller_name="MessageTemplateController",
        path="/message-api/message/template/appointReceiverRole",
        method="POST",
        interface_name="指定消息模板接收角色",
    )

    assert page_result.business_entity == "消息模板"
    assert [(effect.table_name, effect.effect_type) for effect in page_result.effects] == [
        ("cs_message_template", "select")
    ]
    assert menu_result.controller_method == "getMenuTreeByUserId"
    assert menu_result.crud_type == "read"
    assert menu_result.effects == ()
    assert role_result.controller_method == "appointReceiverRole"
    assert role_result.crud_type == "read"
    assert role_result.effects == ()


def test_job_client_analyzer_supports_literal_sql_ids_and_xxl_tables(tmp_path: Path) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-job-client-service/c12-mtp-job-client-biz/"
        "src/main/java/com/example/"
    )
    sql = (
        "backend/c12-mtp/c12-mtp-job-client-service/c12-mtp-job-client-biz/"
        "src/main/resources/sql-ext/job/"
    )
    _write(
        tmp_path,
        java + "Job.java",
        '@Table(name = "xxl_job_info") public class Job {}',
    )
    _write(
        tmp_path,
        java + "JobController.java",
        """
        public class JobController {
            private JobService jobService;
            @PostMapping("/page")
            public Object page(Object condition) { return jobService.page(condition); }
            @PostMapping("/triggerJob")
            public Object triggerJob(Object item) { return remoteService.triggerTask(item); }
            @PostMapping("/exportTemplate")
            public void exportTemplate(Object response) {}
        }
        """,
    )
    _write(
        tmp_path,
        java + "JobService.java",
        """
        public class JobService {
            private JobDao dao;
            public Object page(Object condition) { return dao.page(condition); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "JobDao.java",
        """
        public class JobDao {
            private SqlExecutor sqlExecutor;
            public Object page(Object condition) {
                return sqlExecutor.page(Job.class, "job_page", condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "JobClientAdminSqlId.java",
        "public class JobClientAdminSqlId {}",
    )
    _write(tmp_path, sql + "job_page.sql", "select * from xxl_job_info")

    analyzer = JobClientApiSourceAnalyzer(tmp_path)
    page_result = analyzer.analyze(
        controller_name="JobController",
        path="/job-client-api/job/page",
        method="POST",
        interface_name="分页查询定时任务",
    )
    trigger_result = analyzer.analyze(
        controller_name="JobController",
        path="/job-client-api/job/triggerJob",
        method="POST",
        interface_name="触发定时任务",
    )
    export_result = analyzer.analyze(
        controller_name="JobController",
        path="/job-client-api/job/exportTemplate",
        method="POST",
        interface_name="导出定时任务模板",
    )

    assert page_result.business_entity == "定时任务"
    assert [(effect.table_name, effect.effect_type) for effect in page_result.effects] == [
        ("xxl_job_info", "select")
    ]
    assert page_result.effects[0].sql_statement_id == "job_page"
    assert trigger_result.crud_type == "update"
    assert export_result.crud_type == "read"


def test_trace_analyzer_keeps_remote_aggregation_without_local_tables(tmp_path: Path) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-trace-service/c12-mtp-trace-biz/"
        "src/main/java/com/example/"
    )
    _write(
        tmp_path,
        java + "MapTrackAdminController.java",
        """
        public class MapTrackAdminController {
            private MapTrackAdminService mapTrackAdminService;
            @PostMapping("/overview")
            public Object overview(Object condition) {
                return mapTrackAdminService.adminOverview(condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "MapTrackAdminService.java",
        """
        public class MapTrackAdminService {
            private RemoteBasicService remoteBasicService;
            public Object adminOverview(Object condition) {
                return remoteBasicService.getTraceEntrustedDetail(condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "TraceSqlId.java",
        "public interface TraceSqlId {}",
    )

    result = TraceApiSourceAnalyzer(tmp_path).analyze(
        controller_name="MapTrackAdminController",
        path="/trace-api/admin/track/overview",
        method="POST",
        interface_name="查询运输轨迹概览",
    )

    assert result.controller_method == "overview"
    assert result.business_entity == "运输轨迹"
    assert result.crud_type == "read"
    assert result.effects == ()


def test_message_analyzer_resolves_inner_api_controller_alias(tmp_path: Path) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-message-service/c12-mtp-message-biz/"
        "src/main/java/com/example/"
    )
    _write(
        tmp_path,
        java + "MessageApi.java",
        """
        public class MessageApi {
            private MessageService messageService;
            @PostMapping("/send")
            public Object messageSend(Object request) {
                return messageService.sendMessage(request);
            }
            @PostMapping("/batchSend")
            public Object messageBatchSend(Object request) {
                return messageService.batchSendMessage(request);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "MessageService.java",
        """
        public class MessageService {
            private RemoteUserService remoteUserService;
            public Object sendMessage(Object request) {
                return remoteUserService.getUser(request);
            }
            public Object batchSendMessage(Object request) {
                return sendMessage(request);
            }
        }
        """,
    )
    _write(tmp_path, java + "MessageSqlId.java", "public interface MessageSqlId {}")

    result = MessageApiSourceAnalyzer(tmp_path).analyze(
        controller_name="MessageApiController",
        path="/inner/message/send",
        method="POST",
        interface_name="发送消息",
    )
    batch_result = MessageApiSourceAnalyzer(tmp_path).analyze(
        controller_name="MessageApiController",
        path="/inner/message/batchSend",
        method="POST",
        interface_name="批量发送消息",
    )

    assert result.controller_found is True
    assert result.controller_method == "messageSend"
    assert result.business_entity == "内部消息"
    assert result.crud_type == "create"
    assert batch_result.controller_method == "messageBatchSend"
    assert batch_result.crud_type == "create"


def test_external_interface_analyzer_traces_jpa_repository_tables(tmp_path: Path) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-external-interface-service/"
        "c12-mtp-external-interface-biz/src/main/java/com/example/"
    )
    _write(
        tmp_path,
        java + "FeeFeebill.java",
        '@Table(name = "fee_feebills", schema = "hhggk") class FeeFeebill {}',
    )
    _write(
        tmp_path,
        java + "FeeFeeBillDao.java",
        "public interface FeeFeeBillDao extends JpaRepository<FeeFeebill, Long> {}",
    )
    _write(
        tmp_path,
        java + "FeeFeeBillService.java",
        """
        public class FeeFeeBillService {
            private FeeFeeBillDao feeFeeBillDao;
            public Object getList() { return feeFeeBillDao.findAll(); }
            public Object save(Object item) { return feeFeeBillDao.save(item); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "FeeFeeBillController.java",
        """
        public class FeeFeeBillController {
            private FeeFeeBillService feeFeeBillService;
            @GetMapping("/get")
            public Object getList() { return feeFeeBillService.getList(); }
            @PostMapping("/save")
            public Object save(Object item) { return feeFeeBillService.save(item); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "ExternalInterfaceRolePermissionController.java",
        """
        public class ExternalInterfaceRolePermissionController {
            private RemoteRolePermissionService remoteRolePermissionService;
            @PostMapping("getMenuTreeByUserId")
            public Object getMenuTreeByUserId() {
                return remoteRolePermissionService.getMenuTreeByCondition();
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "ExternalInterfaceSqlId.java",
        "public interface ExternalInterfaceSqlId {}",
    )

    analyzer = ExternalInterfaceApiSourceAnalyzer(tmp_path)
    get_result = analyzer.analyze(
        controller_name="FeeFeeBillController",
        path="/external-interface-api/fee/get",
        method="GET",
        interface_name="查询费用账单",
    )
    save_result = analyzer.analyze(
        controller_name="FeeFeeBillController",
        path="/external-interface-api/fee/save",
        method="POST",
        interface_name="保存费用账单",
    )
    menu_result = analyzer.analyze(
        controller_name="ExternalInterfaceRolePermissionController",
        path=(
            "/external-interface-api/admin/api/system/rolePermission/"
            "getMenuTreeByUserId"
        ),
        method="POST",
        interface_name="查询用户菜单树",
    )

    assert get_result.business_entity == "港口作业费用账单"
    assert [(effect.table_name, effect.effect_type) for effect in get_result.effects] == [
        ("fee_feebills", "select")
    ]
    assert save_result.crud_type == "update"
    assert [(effect.table_name, effect.effect_type) for effect in save_result.effects] == [
        ("fee_feebills", "upsert")
    ]
    assert menu_result.crud_type == "read"
    assert menu_result.business_entity == "用户菜单权限"
    assert menu_result.effects == ()


def test_external_interface_analyzer_corrects_zhiyun_location_alias(
    tmp_path: Path,
) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-external-interface-service/"
        "c12-mtp-external-interface-biz/src/main/java/com/example/"
    )
    _write(
        tmp_path,
        java + "RailwayTransportController.java",
        """
        public class RailwayTransportController {
            private RailwayTransportService railwayTransportService;
            @PostMapping({"/railwayTransLocation", "/railwayTransportLocation"})
            public Object getRailwayTransportLocation(Object request) {
                return railwayTransportService.queryRailwayLocation(request);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "RailwayTransportService.java",
        """
        public class RailwayTransportService {
            private ZhiyunOpenApiService zhiyunOpenApiService;
            public Object queryRailwayLocation(Object request) {
                return zhiyunOpenApiService.railwayTransLocation(request);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "ExternalInterfaceSqlId.java",
        "public interface ExternalInterfaceSqlId {}",
    )

    analyzer = ExternalInterfaceApiSourceAnalyzer(tmp_path)
    legacy_path = analyzer.analyze(
        controller_name="RailwayTransportController",
        path="/zhiyun/railwayTransLocation",
        method="POST",
        interface_name="上报铁路运输位置",
    )
    canonical_path = analyzer.analyze(
        controller_name="RailwayTransportController",
        path="/zhiyun/railwayTransportLocation",
        method="POST",
        interface_name="查询铁路运输位置",
    )

    assert legacy_path.controller_method == "getRailwayTransportLocation"
    assert legacy_path.crud_type == "read"
    assert legacy_path.business_action == "查询铁路运输位置"
    assert "上报铁路运输位置" not in legacy_path.aliases
    assert legacy_path.effects == ()
    assert canonical_path.controller_method == "getRailwayTransportLocation"
    assert canonical_path.crud_type == "read"


def test_external_interface_analyzer_keeps_remote_sms_without_local_tables(
    tmp_path: Path,
) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-external-interface-service/"
        "c12-mtp-external-interface-biz/src/main/java/com/example/"
    )
    _write(
        tmp_path,
        java + "SmsController.java",
        """
        public class SmsController {
            private SmsService smsService;
            @PostMapping("/send")
            public Object send(Object item) { return smsService.send(item); }
        }
        """,
    )
    _write(
        tmp_path,
        java + "SmsService.java",
        """
        public class SmsService {
            private HttpUtils httpUtils;
            public Object send(Object item) {
                return httpUtils.httpPost(item);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "ExternalInterfaceSqlId.java",
        "public interface ExternalInterfaceSqlId {}",
    )

    result = ExternalInterfaceApiSourceAnalyzer(tmp_path).analyze(
        controller_name="SmsController",
        path="/sms/send",
        method="POST",
        interface_name="发送短信",
    )

    assert result.controller_method == "send"
    assert result.business_entity == "短信"
    assert result.crud_type == "create"
    assert result.effects == ()


def test_declaration_interface_analyzer_keeps_remote_menu_without_local_tables(
    tmp_path: Path,
) -> None:
    java = (
        "backend/c12-mtp/c12-mtp-declaration-interface-service/"
        "c12-mtp-declaration-interface-biz/src/main/java/com/example/"
    )
    _write(
        tmp_path,
        java + "DeclarationInterfaceRolePermissionController.java",
        """
        public class DeclarationInterfaceRolePermissionController {
            private RemoteRolePermissionService remoteRolePermissionService;
            @PostMapping("getMenuTreeByUserId")
            public Object getMenuTreeByUserId() {
                return remoteRolePermissionService.getMenuTreeByCondition();
            }
        }
        """,
    )
    _write(tmp_path, java + "SqlId.java", "public interface SqlId {}")

    result = DeclarationInterfaceApiSourceAnalyzer(tmp_path).analyze(
        controller_name="DeclarationInterfaceRolePermissionController",
        path=(
            "/declaration-interface-api/admin/api/system/rolePermission/"
            "getMenuTreeByUserId"
        ),
        method="POST",
        interface_name="查询用户菜单树",
    )

    assert result.controller_method == "getMenuTreeByUserId"
    assert result.business_entity == "申报集成用户菜单权限"
    assert result.crud_type == "read"
    assert result.effects == ()


def test_web_admin_analyzer_supports_flat_layout_and_implicit_sql_constants(
    tmp_path: Path,
) -> None:
    java = "backend/c12-mtp/c12-mtp-web-service/src/main/java/com/example/"
    sql = (
        "backend/c12-mtp/c12-mtp-web-service/src/main/resources/sql-ext/driver/"
    )
    _write(
        tmp_path,
        java + "Driver.java",
        '@Table(name = "cs_mtp_driver") public class Driver {}',
    )
    _write(
        tmp_path,
        java + "DriverController.java",
        """
        public class DriverController {
            private DriverService driverService;
            @PostMapping("/page")
            public Object page(Object condition) {
                return driverService.page(condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "DriverService.java",
        """
        public class DriverService {
            private MtpDriverDao mtpDriverDao;
            public Object page(Object condition) {
                return mtpDriverDao.page(condition);
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "MtpDriverDao.java",
        """
        public class MtpDriverDao extends ModuleBaseDaoSupport<Driver, Long> {
            public Object page(Object condition) {
                return sqlExecutor.page(
                    Driver.class,
                    BtTransportSqlId.DRIVER_QUERY_GET_PAGE_LIST,
                    condition
                );
            }
        }
        """,
    )
    _write(
        tmp_path,
        java + "BtTransportSqlId.java",
        """
        public interface BtTransportSqlId {
            String DRIVER_QUERY_GET_PAGE_LIST = "driver_query_getPageList";
        }
        """,
    )
    _write(
        tmp_path,
        sql + "driver_query_getPageList.sql",
        "select * from cs_mtp_driver",
    )
    _write(
        tmp_path,
        java + "AccountOverviewController.java",
        """
        public class AccountOverviewController {
            private AccountOverviewService accountOverviewService;
            @PostMapping
            public Object overview() {
                return accountOverviewService.getOverview();
            }
            private Object getRoleCodes() { return null; }
        }
        """,
    )

    result = WebAdminApiSourceAnalyzer(tmp_path).analyze(
        controller_name="DriverController",
        path="/admin/driver/page",
        method="POST",
        interface_name="分页查询司机",
    )
    overview = WebAdminApiSourceAnalyzer(tmp_path).analyze(
        controller_name="AccountOverviewController",
        path="/admin/workbench/accountOverview",
        method="POST",
        interface_name="查询账户概览",
    )

    assert result.controller_method == "page"
    assert result.business_entity == "司机"
    assert result.crud_type == "read"
    assert [(effect.table_name, effect.effect_type) for effect in result.effects] == [
        ("cs_mtp_driver", "select")
    ]
    assert result.effects[0].sql_statement_id == "driver_query_getPageList"
    assert overview.controller_method == "overview"
    assert overview.crud_type == "read"
