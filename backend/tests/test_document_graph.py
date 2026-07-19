def test_shortest_reachable_depths_handles_cycles_and_orphans() -> None:
    from context_router.services.document_graph import shortest_reachable_depths

    depths = shortest_reachable_depths(
        root_id="entry",
        outgoing={
            "entry": ["business", "shared"],
            "business": ["database", "shared"],
            "database": ["business"],
            "shared": [],
            "orphan": [],
        },
    )

    assert depths == {
        "entry": 1,
        "business": 2,
        "shared": 2,
        "database": 3,
    }
