from context_router.scripts.seed_interface_semantics import SEEDS


def test_entrusted_semantic_seeds_are_unique_and_source_backed() -> None:
    identities = {(seed.method, seed.path) for seed in SEEDS}

    assert len(identities) == len(SEEDS)
    assert all(seed.source_file.endswith("Service.java") for seed in SEEDS)
    assert all(seed.call_path[-1].startswith("cs_dsly_order_entrusted:") for seed in SEEDS)
    assert all(seed.fingerprint for seed in SEEDS)


def test_entrusted_semantic_seeds_cover_core_crud_and_quote_intent() -> None:
    by_path = {seed.path: seed for seed in SEEDS}

    assert by_path["/order-api/portal/entrusted/saveEntrusted"].crud_type == "create"
    assert by_path["/order-api/admin/entrusted/page"].crud_type == "read"
    assert by_path["/order-api/admin/entrusted/save"].crud_type == "update"
    assert by_path["/order-api/admin/entrusted/deleteByIds/{ids}"].crud_type == "delete"
    quote = by_path["/order-api/admin/entrusted/quote/save"]
    assert "发起委托需求报价" in quote.aliases
    assert quote.effect_type == "update"
