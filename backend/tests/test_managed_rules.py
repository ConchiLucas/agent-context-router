from context_router.repositories.managed_rule_repository import InMemoryManagedRuleRepository
from context_router.schemas.managed_rules import ManagedRuleWrite
from context_router.services.managed_rules import SEED_RULES, ManagedRulesError, ManagedRulesService


def test_empty_store_seeds_control_plane_rules() -> None:
    service = ManagedRulesService(InMemoryManagedRuleRepository())

    listing = service.list_rules()

    assert [item.slug for item in listing.rules] == [spec.slug for spec in SEED_RULES]
    assert [item.title for item in listing.rules] == [spec.title for spec in SEED_RULES]
    prepare_rules = service.list_prepare_rules()
    assert [item.body for item in prepare_rules] == [spec.body for spec in SEED_RULES]
    assert all(item.id for item in prepare_rules)
    assert "以精简并删除冗余代码为荣" in prepare_rules[0].body


def test_create_update_and_delete_user_rule() -> None:
    service = ManagedRulesService(InMemoryManagedRuleRepository())
    service.list_rules()

    created = service.create_rule(ManagedRuleWrite(title="  额外约束  ", body="  先读 prepare  "))
    assert created.slug.startswith("user-")
    assert created.title == "额外约束"
    assert created.body == "先读 prepare"
    assert created.sort_order > SEED_RULES[-1].sort_order

    updated = service.update_rule(
        created.id,
        ManagedRuleWrite(title="更新后的标题", body="更新后的正文"),
    )
    assert updated.id == created.id
    assert updated.title == "更新后的标题"
    assert updated.body == "更新后的正文"
    assert updated.slug == created.slug

    service.delete_rule(created.id)
    remaining = {item.id for item in service.list_rules().rules}
    assert created.id not in remaining
    assert len(remaining) == len(SEED_RULES)


def test_deleting_one_seed_does_not_restore_it_on_list() -> None:
    service = ManagedRulesService(InMemoryManagedRuleRepository())
    service.list_rules()
    extra = service.create_rule(ManagedRuleWrite(title="保留", body="避免空表回种"))
    first = next(item for item in service.list_rules().rules if item.slug == SEED_RULES[0].slug)

    service.delete_rule(first.id)

    slugs = [item.slug for item in service.list_rules().rules]
    assert first.slug not in slugs
    assert slugs == [extra.slug]


def test_update_missing_rule_is_not_found() -> None:
    service = ManagedRulesService(InMemoryManagedRuleRepository())
    try:
        service.update_rule("missing", ManagedRuleWrite(title="标题", body="正文"))
    except ManagedRulesError as exc:
        assert exc.not_found
    else:
        raise AssertionError("expected missing rule")
