from context_router.services.interface_intent_matching import InterfaceIntentMatcher


def _candidate(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "name": "分页查询委托报价",
        "path": "/order-api/admin/entrusted/quote/page",
        "crud_type": "read",
        "business_entity": "委托需求报价",
        "business_action": "分页查询委托报价",
        "business_scenario": "运营端查询委托需求报价列表",
        "aliases": ["分页查询委托需求报价", "委托需求报价列表"],
        "positive_examples": ["查询委托需求的报价列表"],
        "negative_examples": ["新增委托需求报价"],
        "intent_confidence": 95,
        "table_effects": [],
    }
    value.update(overrides)
    return value


def test_interface_discovery_is_distinguished_from_execution() -> None:
    discovery = InterfaceIntentMatcher.analyze("查询委托需求报价的接口")
    execution = InterfaceIntentMatcher.analyze("在 UAT 发起一条委托需求报价")

    assert discovery.goal == "discover"
    assert discovery.business_entity == "委托需求报价"
    assert discovery.desired_crud == "read"
    assert discovery.result_shape == "page"
    assert execution.goal == "execute"
    assert execution.business_entity == "一条委托需求报价"
    assert execution.desired_crud == "create"


def test_structured_business_semantics_outrank_wrong_crud() -> None:
    intent = InterfaceIntentMatcher.analyze("分页查询委托需求报价")
    read_match = InterfaceIntentMatcher.score(intent, _candidate())
    create_match = InterfaceIntentMatcher.score(
        intent,
        _candidate(
            name="新增委托报价",
            path="/order-api/admin/entrusted/quote/save",
            crud_type="create",
            business_action="新增委托报价",
            aliases=["新增委托需求报价"],
            positive_examples=["发起委托报价"],
            negative_examples=["查询委托需求报价"],
        ),
    )

    assert read_match.score > create_match.score
    assert "CRUD 匹配：read" in read_match.reasons
    assert "期望 read，候选为 create" in create_match.mismatches
    assert "命中负向示例" in create_match.mismatches


def test_result_shape_separates_page_and_detail_candidates() -> None:
    intent = InterfaceIntentMatcher.analyze("分页查询委托需求报价")
    page = InterfaceIntentMatcher.score(intent, _candidate())
    detail = InterfaceIntentMatcher.score(
        intent,
        _candidate(
            name="查询委托报价详情",
            path="/order-api/admin/entrusted/quote/getById",
            business_action="查询委托报价详情",
        ),
    )

    assert page.score > detail.score
    assert "接口形态匹配：page" in page.reasons


def test_explicit_create_intent_outranks_read_candidate() -> None:
    intent = InterfaceIntentMatcher.analyze("货主端发起委托需求报价")
    read_match = InterfaceIntentMatcher.score(
        intent,
        _candidate(
            name="按 ID 查询委托报价",
            business_scenario="门户端查询委托需求报价",
            crud_type="read",
        ),
    )
    create_match = InterfaceIntentMatcher.score(
        intent,
        _candidate(
            name="保存委托报价",
            business_action="保存委托报价",
            business_scenario="运营人员为委托需求创建报价",
            aliases=["发起委托需求报价"],
            crud_type="create",
        ),
    )

    assert create_match.score > read_match.score
    assert any(
        item["category"] == "crud" and item["delta"] == -180
        for item in read_match.score_breakdown
    )
