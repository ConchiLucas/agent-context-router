from datetime import UTC, datetime

from context_router.interface_search.domain import (
    QueryIntent,
    ScoreBreakdown,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from context_router.repositories.database_environment_repository import (
    InMemoryDatabaseEnvironmentRepository,
)
from context_router.repositories.interface_prompt_match_repository import (
    InMemoryInterfacePromptMatchRepository,
)
from context_router.repositories.mcp_tool_call_repository import McpToolCallRecord
from context_router.repositories.workspace_repository import InMemoryWorkspaceRepository
from context_router.schemas.interface_prompt_matches import (
    InterfacePromptClientResultImport,
    InterfacePromptClientResultImportItem,
    InterfacePromptIdentity,
    InterfacePromptMatchCandidate,
    InterfacePromptMatchCreate,
)
from context_router.services.interface_prompt_clients import (
    InterfaceClientResultCounts,
    PostgresInterfaceClientJudgmentFinder,
    ReturnedPromptKeys,
    _returned_prompt_keys,
    build_client_judgment,
    prompt_query_sha256,
)
from context_router.services.interface_prompt_matches import (
    InterfacePromptMatchError,
    InterfacePromptMatchService,
)


class FakeSearchService:
    def __init__(self, response: SearchResponse) -> None:
        self.response = response
        self.repository = _EmptyEndpointRepository()
        self.requests: list[SearchRequest] = []

    def search(self, request: SearchRequest) -> SearchResponse:
        self.requests.append(request)
        return self.response


class _EmptyEndpointRepository:
    def get(self, endpoint_id: str):
        return None


class _FakeEndpoint:
    def __init__(
        self,
        interface_id: str,
        method: str,
        path: str,
        title: str,
        service: str = "c12-mtp",
    ) -> None:
        self.id = interface_id
        self.method = method
        self.path = path
        self.title = title
        self.service = service


class _CatalogRepository:
    def __init__(self, items: dict[str, _FakeEndpoint]) -> None:
        self._items = items

    def get(self, endpoint_id: str):
        return self._items.get(endpoint_id)


def _score(*, exact: float = 0, total: float = 0.4) -> ScoreBreakdown:
    return ScoreBreakdown(
        exact=exact,
        lexical=0,
        vector=0,
        classification=0,
        rerank=0,
        rrf=0,
        total=total,
    )


def _hit(
    *,
    interface_id: str,
    title: str,
    path: str,
    method: str = "POST",
    service: str = "c12-portal",
    audiences: list[str] | None = None,
    domains: list[str] | None = None,
    resource: str = "dispatchOrder",
    actions: list[str] | None = None,
    reasons: list[str] | None = None,
    matched_slots: list[str] | None = None,
    exact: float = 0,
    total: float = 0.4,
    rank: int = 1,
) -> SearchHit:
    return SearchHit(
        rank=rank,
        retrieval_rank=rank,
        interface_id=interface_id,
        workspace_id="ws-1",
        project="c12-portal",
        service=service,
        method=method,
        path=path,
        operation_id="",
        title=title,
        purpose=title,
        audiences=audiences or ["portal"],
        domains=domains or ["dispatch"],
        scenarios=[],
        resource=resource,
        actions=actions or ["load"],
        confidence=total,
        score=_score(exact=exact, total=total),
        reasons=reasons or [f"匹配 {title}"],
        matched_slots=matched_slots or [],
    )


def _response(hits: list[SearchHit], *, top_margin: float = 0.02) -> SearchResponse:
    return SearchResponse(
        search_id="search-1",
        workspace_id="ws-1",
        query="门户端装货接口",
        intent=QueryIntent(normalized_query="门户端装货接口"),
        hits=hits,
        confidence="medium",
        should_clarify=False,
        top_margin=top_margin,
        candidate_count=len(hits),
        elapsed_ms=8,
    )


def _service(
    response: SearchResponse,
    client_finder=None,
) -> tuple[InterfacePromptMatchService, FakeSearchService]:
    workspaces = InMemoryWorkspaceRepository()
    workspaces.create_workspace(
        workspace_id="ws-1",
        name="攀枝花",
        workspace_type="公司项目",
        root_path="/tmp/pzh",
    )
    search = FakeSearchService(response)
    service = InterfacePromptMatchService(
        InMemoryInterfacePromptMatchRepository(),
        workspaces,
        InMemoryDatabaseEnvironmentRepository(),
        search,
        client_finder=client_finder,
    )
    return service, search


def test_unique_hit_is_resolved_and_persisted() -> None:
    hit = _hit(
        interface_id="unique-1",
        title="精确路径",
        path="/highway-api/portal/dispatchOrder/load",
        exact=0.99,
        total=0.99,
    )
    service, search = _service(_response([hit], top_margin=0.4))

    created = service.create_match(
        InterfacePromptMatchCreate(
            workspace_id="ws-1",
            environment_key="local",
            prompt="  /highway-api/portal/dispatchOrder/load  ",
        )
    )

    assert created.verdict == "resolved"
    assert created.first_interface_id == "unique-1"
    assert created.remaining_count == 0
    assert created.differing_dimensions == []
    assert created.candidates[0].title == "精确路径"
    assert created.expected is None
    assert [item.client for item in created.clients] == [
        "codex",
        "codex-root",
        "codex-astra",
        "cursor",
        "antigravity",
        "grok-heavy",
    ]
    assert {item.status for item in created.clients} == {"missing"}
    assert search.requests[0].top_k == 20
    listed = service.list_matches("ws-1")
    assert [item.id for item in listed.items] == [created.id]
    assert listed.total == 1
    assert listed.page == 1
    assert listed.page_size == 20


def test_imported_client_result_overrides_trace_reconstruction() -> None:
    hit = _hit(interface_id="chosen-1", title="模型所选接口", path="/chosen")
    service, search = _service(_response([hit]))
    search.repository = _CatalogRepository(
        {"chosen-1": _FakeEndpoint("chosen-1", "POST", "/chosen", "模型所选接口")}
    )
    created = service.create_match(
        InterfacePromptMatchCreate(workspace_id="ws-1", prompt="盲测提示词")
    )

    imported = service.import_client_results(
        InterfacePromptClientResultImport(
            workspace_id="ws-1",
            records=[
                InterfacePromptClientResultImportItem(
                    record_id=created.id,
                    client="cursor",
                    task_id=77,
                    batch_id="batch-0001",
                    source_file="batch-0001.result.cursor.json",
                    status="selected",
                    selected_interface_id="chosen-1",
                    searched=True,
                    detail_read=True,
                )
            ],
        )
    )

    listed = service.list_matches("ws-1", prioritize_returned_for="cursor")
    cursor = next(item for item in listed.items[0].clients if item.client == "cursor")
    assert imported.imported_count == 1
    assert cursor.status == "selected"
    assert cursor.task_id == 77
    assert cursor.selected_interface_id == "chosen-1"
    assert cursor.selected_path == "/chosen"

    deleted = service.delete_stored_client_results("ws-1", client="cursor", expected_count=1)
    after_delete = service.list_matches("ws-1")
    cursor = next(item for item in after_delete.items[0].clients if item.client == "cursor")
    assert deleted.matched_result_count == 1
    assert deleted.deleted_result_count == 1
    assert cursor.status == "missing"


def test_imported_grok_heavy_result_is_stored_as_an_independent_client() -> None:
    hit = _hit(interface_id="chosen-1", title="模型所选接口", path="/chosen")
    service, search = _service(_response([hit]))
    search.repository = _CatalogRepository(
        {"chosen-1": _FakeEndpoint("chosen-1", "POST", "/chosen", "模型所选接口")}
    )
    created = service.create_match(
        InterfacePromptMatchCreate(workspace_id="ws-1", prompt="Grok Heavy 盲测提示词")
    )

    imported = service.import_client_results(
        InterfacePromptClientResultImport(
            workspace_id="ws-1",
            records=[
                InterfacePromptClientResultImportItem(
                    record_id=created.id,
                    client="grok-heavy",
                    task_id=88,
                    batch_id="batch-0001",
                    model="grok-heavy",
                    source_file="batch-0001.result.grok-heavy.json",
                    status="selected",
                    selected_interface_id="chosen-1",
                    searched=True,
                    detail_read=True,
                )
            ],
        )
    )

    listed = service.list_matches("ws-1", prioritize_returned_for="grok-heavy")
    grok = next(item for item in listed.items[0].clients if item.client == "grok-heavy")
    assert imported.imported_count == 1
    assert grok.status == "selected"
    assert grok.task_id == 88
    assert grok.selected_interface_id == "chosen-1"
    assert grok.selected_path == "/chosen"


def test_import_rejects_selected_result_without_detail_evidence() -> None:
    service, _search = _service(_response([]))
    created = service.create_match(
        InterfacePromptMatchCreate(workspace_id="ws-1", prompt="盲测提示词")
    )

    try:
        service.import_client_results(
            InterfacePromptClientResultImport(
                workspace_id="ws-1",
                records=[
                    InterfacePromptClientResultImportItem(
                        record_id=created.id,
                        client="codex",
                        task_id=77,
                        batch_id="batch-0001",
                        source_file="result.json",
                        status="selected",
                        selected_interface_id="chosen-1",
                    )
                ],
            )
        )
    except InterfacePromptMatchError as exc:
        assert "详情读取证据" in str(exc)
    else:
        raise AssertionError("expected missing detail evidence to be rejected")


def test_list_matches_pages_every_row() -> None:
    service, _search = _service(
        _response([_hit(interface_id="unique-1", title="精确路径", path="/demo")])
    )
    created = [
        service.create_match(
            InterfacePromptMatchCreate(workspace_id="ws-1", prompt=f"提示词 {index}")
        )
        for index in range(3)
    ]

    first = service.list_matches("ws-1", page=1, page_size=2)
    second = service.list_matches("ws-1", page=2, page_size=2)
    ids = [item.id for item in first.items] + [item.id for item in second.items]

    assert first.total == 3
    assert first.page == 1
    assert first.page_size == 2
    assert [item.id for item in first.items] == [created[2].id, created[1].id]
    assert [item.id for item in second.items] == [created[0].id]
    assert ids == [created[2].id, created[1].id, created[0].id]


class _PriorityFinder:
    def find_latest_calls(self, *, workspace_id: str, record_id: str, prompt: str):
        return {}

    def returned_prompt_keys(self, *, workspace_id: str, client: str) -> ReturnedPromptKeys:
        assert workspace_id == "ws-1"
        assert client == "antigravity"
        return ReturnedPromptKeys(digests=frozenset({prompt_query_sha256("提示词 0")}))


class _ResetFinder:
    def __init__(self) -> None:
        self.deleted = False

    def find_latest_calls(self, *, workspace_id: str, record_id: str, prompt: str):
        return {}

    def returned_prompt_keys(self, *, workspace_id: str, client: str) -> ReturnedPromptKeys:
        return ReturnedPromptKeys()

    def preview_reset(self, *, workspace_id: str, client: str) -> InterfaceClientResultCounts:
        assert workspace_id == "ws-1"
        assert client == "antigravity"
        return InterfaceClientResultCounts(task_count=7, tool_call_count=31)

    def reset_results(
        self,
        *,
        workspace_id: str,
        client: str,
        expected_task_count: int,
        expected_tool_call_count: int,
    ) -> InterfaceClientResultCounts:
        assert expected_task_count == 7
        assert expected_tool_call_count == 31
        self.deleted = True
        return InterfaceClientResultCounts(task_count=7, tool_call_count=31)


class _RecordScopedFinder:
    def __init__(self) -> None:
        self.hits: dict[str, dict[str, tuple[int, list[McpToolCallRecord]]]] = {}
        self.requests: list[tuple[str, str, str]] = []

    def find_latest_calls(self, *, workspace_id: str, record_id: str, prompt: str):
        self.requests.append((workspace_id, record_id, prompt))
        return self.hits.get(record_id, {})

    def returned_prompt_keys(self, *, workspace_id: str, client: str) -> ReturnedPromptKeys:
        return ReturnedPromptKeys()

    def preview_reset(self, *, workspace_id: str, client: str) -> InterfaceClientResultCounts:
        return InterfaceClientResultCounts()


class _FinderResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self.rows[0] if self.rows else None


class _FinderConnection:
    def __init__(
        self,
        *,
        exact_rows: list[tuple[object, ...]],
        prompt_count: int,
        legacy_rows: list[tuple[object, ...]] | None = None,
    ) -> None:
        self.exact_rows = exact_rows
        self.prompt_count = prompt_count
        self.legacy_rows = legacy_rows or []
        self.executed: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def execute(self, statement: str, parameters: tuple[object, ...]) -> _FinderResult:
        self.executed.append(statement)
        if "call.trace_context->>'item_id'" in statement:
            return _FinderResult(self.exact_rows)
        if "SELECT count(*)" in statement:
            return _FinderResult([(self.prompt_count,)])
        if "call.request_summary->>'query_sha256'" in statement:
            assert "call.trace_context IS NULL" in statement
            return _FinderResult(self.legacy_rows)
        raise AssertionError(f"unexpected query: {statement}")


class _FinderToolCalls:
    def __init__(self, calls: list[McpToolCallRecord]) -> None:
        self.calls = calls
        self.requests: list[tuple[int, str | None, str | None]] = []

    def list_calls(
        self,
        task_id: int,
        *,
        run_id: str | None = None,
        item_id: str | None = None,
    ) -> list[McpToolCallRecord]:
        self.requests.append((task_id, run_id, item_id))
        return self.calls


def test_postgres_finder_uses_record_id_client_and_latest_run(monkeypatch) -> None:
    connection = _FinderConnection(
        exact_rows=[("cursor", 77, "run-new", 900)],
        prompt_count=2,
        legacy_rows=[("antigravity", 66)],
    )
    tool_calls = _FinderToolCalls([_call("search_forwarding_interfaces")])
    monkeypatch.setattr(
        "context_router.services.interface_prompt_clients.psycopg.connect",
        lambda _database_url: connection,
    )
    finder = PostgresInterfaceClientJudgmentFinder("postgresql://test", tool_calls)

    found = finder.find_latest_calls(
        workspace_id="ws-1",
        record_id="record-new",
        prompt="完全相同的提示词",
    )

    assert set(found) == {"cursor"}
    assert found["cursor"][0] == 77
    assert tool_calls.requests == [(77, "run-new", "record-new")]
    assert not any(
        "call.request_summary->>'query_sha256'" in query for query in connection.executed
    )


def test_postgres_finder_only_uses_prompt_fallback_for_unique_legacy_record(
    monkeypatch,
) -> None:
    connection = _FinderConnection(
        exact_rows=[],
        prompt_count=1,
        legacy_rows=[("antigravity", 66)],
    )
    tool_calls = _FinderToolCalls([_call("search_forwarding_interfaces")])
    monkeypatch.setattr(
        "context_router.services.interface_prompt_clients.psycopg.connect",
        lambda _database_url: connection,
    )
    finder = PostgresInterfaceClientJudgmentFinder("postgresql://test", tool_calls)

    found = finder.find_latest_calls(
        workspace_id="ws-1",
        record_id="legacy-record",
        prompt="唯一旧提示词",
    )

    assert set(found) == {"antigravity"}
    assert found["antigravity"][0] == 66
    assert tool_calls.requests == [(66, None, None)]


def test_postgres_finder_does_not_fallback_for_duplicate_prompt(monkeypatch) -> None:
    connection = _FinderConnection(
        exact_rows=[],
        prompt_count=2,
        legacy_rows=[("antigravity", 66)],
    )
    tool_calls = _FinderToolCalls([_call("search_forwarding_interfaces")])
    monkeypatch.setattr(
        "context_router.services.interface_prompt_clients.psycopg.connect",
        lambda _database_url: connection,
    )
    finder = PostgresInterfaceClientJudgmentFinder("postgresql://test", tool_calls)

    found = finder.find_latest_calls(
        workspace_id="ws-1",
        record_id="new-version",
        prompt="重复提示词",
    )

    assert found == {}
    assert tool_calls.requests == []
    assert not any(
        "call.request_summary->>'query_sha256'" in query for query in connection.executed
    )

    def reset_results(
        self,
        *,
        workspace_id: str,
        client: str,
        expected_task_count: int,
        expected_tool_call_count: int,
    ) -> InterfaceClientResultCounts:
        return InterfaceClientResultCounts()


def test_reset_only_accepts_antigravity_and_returns_exact_counts() -> None:
    finder = _ResetFinder()
    service, _search = _service(_response([]), client_finder=finder)

    preview = service.preview_client_result_reset("ws-1", client="antigravity")
    deleted = service.reset_client_results(
        "ws-1",
        client="antigravity",
        expected_task_count=7,
        expected_tool_call_count=31,
    )

    assert preview.matched_task_count == 7
    assert preview.deleted_task_count == 0
    assert deleted.deleted_task_count == 7
    assert finder.deleted

    try:
        service.preview_client_result_reset("ws-1", client="codex")
    except InterfacePromptMatchError as exc:
        assert "Antigravity" in str(exc)
    else:
        raise AssertionError("expected codex reset to be rejected")


def test_list_matches_prioritizes_returned_rows_before_pagination() -> None:
    service, _search = _service(
        _response([_hit(interface_id="unique-1", title="精确路径", path="/demo")]),
        client_finder=_PriorityFinder(),
    )
    created = [
        service.create_match(
            InterfacePromptMatchCreate(workspace_id="ws-1", prompt=f"提示词 {index}")
        )
        for index in range(3)
    ]

    first = service.list_matches(
        "ws-1",
        page=1,
        page_size=2,
        prioritize_returned_for="antigravity",
    )

    assert [item.id for item in first.items] == [created[0].id, created[2].id]


def test_same_prompt_records_use_record_scoped_client_judgments() -> None:
    finder = _RecordScopedFinder()
    first_hit = _hit(interface_id="first", title="第一个接口", path="/first", rank=1)
    second_hit = _hit(interface_id="second", title="第二个接口", path="/second", rank=2)
    service, _search = _service(
        _response([first_hit, second_hit]),
        client_finder=finder,
    )
    first = service.create_match(
        InterfacePromptMatchCreate(workspace_id="ws-1", prompt="完全相同的提示词")
    )
    second = service.create_match(
        InterfacePromptMatchCreate(workspace_id="ws-1", prompt="完全相同的提示词")
    )
    finder.hits[first.id] = {
        "cursor": (
            101,
            [
                _call(
                    "read_forwarding_interface_detail",
                    request_summary={"interface_id": "first"},
                )
            ],
        )
    }
    finder.hits[second.id] = {
        "cursor": (
            202,
            [
                _call(
                    "read_forwarding_interface_detail",
                    request_summary={"interface_id": "second"},
                )
            ],
        )
    }

    listed = service.list_matches("ws-1")
    by_id = {item.id: item for item in listed.items}
    first_cursor = next(item for item in by_id[first.id].clients if item.client == "cursor")
    second_cursor = next(item for item in by_id[second.id].clients if item.client == "cursor")

    assert first_cursor.task_id == 101
    assert first_cursor.selected_interface_id == "first"
    assert second_cursor.task_id == 202
    assert second_cursor.selected_interface_id == "second"
    assert ("ws-1", first.id, "完全相同的提示词") in finder.requests
    assert ("ws-1", second.id, "完全相同的提示词") in finder.requests


def test_returned_prompt_keys_use_latest_search_segment() -> None:
    prompt = "门户端查询运输订单"
    digest = prompt_query_sha256(prompt)
    rows = [
        (9, "批量测试", 1, "search_forwarding_interfaces", "ok", {"query_sha256": digest}),
        (
            9,
            "批量测试",
            2,
            "read_forwarding_interface_detail",
            "ok",
            {"interface_id": "first"},
        ),
        (9, "批量测试", 3, "search_forwarding_interfaces", "ok", {"query_sha256": digest}),
    ]

    keys = _returned_prompt_keys(rows)

    assert digest not in keys.digests


def test_close_hits_need_selection_and_keep_difference_line() -> None:
    hits = [
        _hit(
            interface_id="highway",
            title="公路装货",
            path="/highway-api/portal/dispatchOrder/load",
            domains=["highway"],
            reasons=["匹配门户", "匹配装货", "公路域"],
            rank=1,
            total=0.71,
        ),
        _hit(
            interface_id="railway",
            title="铁路装货",
            path="/railway-api/portal/dispatchOrder/load",
            domains=["railway"],
            reasons=["匹配门户", "匹配装货"],
            rank=2,
            total=0.69,
        ),
        _hit(
            interface_id="shipping",
            title="水运装货",
            path="/shipping-api/portal/dispatchOrder/load",
            domains=["shipping"],
            reasons=["匹配门户"],
            rank=3,
            total=0.67,
        ),
        _hit(
            interface_id="extra",
            title="其它装货",
            path="/other/load",
            rank=4,
            total=0.4,
        ),
    ]
    service, _ = _service(_response(hits, top_margin=0.02))

    created = service.create_match(
        InterfacePromptMatchCreate(workspace_id="ws-1", prompt="门户端装货接口")
    )

    assert created.verdict == "needs_selection"
    assert created.first_interface_id == "highway"
    assert created.remaining_count == 1
    assert [item.interface_id for item in created.candidates] == [
        "highway",
        "railway",
        "shipping",
        "extra",
    ]
    assert "domains" in created.differing_dimensions
    assert created.candidates[0].reasons == ["匹配门户", "匹配装货", "公路域"]


def test_empty_hits_are_no_candidate() -> None:
    service, _ = _service(_response([]))

    created = service.create_match(
        InterfacePromptMatchCreate(workspace_id="ws-1", prompt="不存在的接口")
    )

    assert created.verdict == "no_candidate"
    assert created.first_interface_id is None
    assert created.candidates == []
    assert "没有找到" in created.reason


def test_missing_workspace_is_not_found() -> None:
    service, _ = _service(_response([]))
    try:
        service.create_match(InterfacePromptMatchCreate(workspace_id="missing", prompt="装货"))
    except InterfacePromptMatchError as exc:
        assert exc.not_found
    else:
        raise AssertionError("expected missing workspace")


def test_unknown_environment_is_rejected() -> None:
    service, _ = _service(_response([]))
    try:
        service.create_match(
            InterfacePromptMatchCreate(
                workspace_id="ws-1",
                environment_key="staging",
                prompt="装货",
            )
        )
    except InterfacePromptMatchError as exc:
        assert "未登记" in str(exc)
    else:
        raise AssertionError("expected unknown environment")


def _call(
    tool_name: str,
    *,
    status: str = "ok",
    request_summary: dict[str, object] | None = None,
    call_id: int = 1,
) -> McpToolCallRecord:
    return McpToolCallRecord(
        id=call_id,
        task_id=9,
        parent_tool_call_id=None,
        server_name="context-router",
        tool_name=tool_name,
        source="server",
        status=status,  # type: ignore[arg-type]
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        duration_ms=10,
        request_summary=request_summary,
        result_summary=None,
        error_code=None,
    )


def test_client_judgment_selects_last_detail_and_flags_compare() -> None:
    candidate = InterfacePromptMatchCandidate(
        interface_id="highway",
        method="POST",
        path="/highway-api/portal/dispatchOrder/load",
        title="公路装货",
    )
    judgment = build_client_judgment(
        "codex",
        9,
        [
            _call("search_forwarding_interfaces", call_id=1),
            _call(
                "compare_forwarding_interfaces",
                request_summary={"interface_ids": ["highway", "railway"]},
                call_id=2,
            ),
            _call(
                "read_forwarding_interface_detail",
                request_summary={"interface_id": "highway"},
                call_id=3,
            ),
        ],
        {candidate.interface_id: candidate},
    )
    assert judgment.status == "selected"
    assert judgment.selected_interface_id == "highway"
    assert judgment.selected_path == "/highway-api/portal/dispatchOrder/load"
    assert judgment.in_candidates is True
    assert judgment.compared is True
    assert judgment.compared_interface_ids == ["highway", "railway"]


def test_client_judgment_scopes_detail_to_matching_search() -> None:
    highway = InterfacePromptMatchCandidate(
        interface_id="highway",
        method="POST",
        path="/highway-api/portal/dispatchOrder/load",
        title="公路装货",
    )
    bill = InterfacePromptMatchCandidate(
        interface_id="bill",
        method="POST",
        path="/member-api/portal/scts/customer/bill/page",
        title="应收账单",
    )
    calls = [
        _call(
            "search_forwarding_interfaces",
            request_summary={
                "query_sha256": prompt_query_sha256("门户端承运商按公路运输订单号登记装货")
            },
            call_id=1,
        ),
        _call(
            "read_forwarding_interface_detail",
            request_summary={"interface_id": "highway"},
            call_id=2,
        ),
        _call(
            "search_forwarding_interfaces",
            request_summary={
                "query_sha256": prompt_query_sha256("PC客户门户分页查询当前登录客户的应收账单")
            },
            call_id=3,
        ),
        _call(
            "read_forwarding_interface_detail",
            request_summary={"interface_id": "bill"},
            call_id=4,
        ),
    ]
    candidates = {highway.interface_id: highway, bill.interface_id: bill}
    first = build_client_judgment(
        "antigravity",
        9,
        calls,
        candidates,
        prompt="门户端承运商按公路运输订单号登记装货",
    )
    last = build_client_judgment(
        "antigravity",
        9,
        calls,
        candidates,
        prompt="PC客户门户分页查询当前登录客户的应收账单",
    )
    assert first.selected_path == "/highway-api/portal/dispatchOrder/load"
    assert last.selected_path == "/member-api/portal/scts/customer/bill/page"


def test_client_judgment_marks_compare_without_detail_as_clarify() -> None:
    judgment = build_client_judgment(
        "antigravity",
        9,
        [
            _call("search_forwarding_interfaces", call_id=1),
            _call(
                "compare_forwarding_interfaces",
                request_summary={"interface_ids": ["highway", "railway"]},
                call_id=2,
            ),
        ],
        {},
    )
    assert judgment.status == "clarify"
    assert judgment.selected_interface_id is None


def test_create_match_stores_expected_interface() -> None:
    hit = _hit(
        interface_id="unique-1",
        title="精确路径",
        path="/highway-api/portal/dispatchOrder/load",
        exact=0.99,
        total=0.99,
    )
    service, search = _service(_response([hit], top_margin=0.4))
    search.repository = _CatalogRepository(
        {
            "highway": _FakeEndpoint(
                "highway",
                "POST",
                "/highway-api/portal/dispatchOrder/load",
                "公路装货",
            )
        }
    )

    created = service.create_match(
        InterfacePromptMatchCreate(
            workspace_id="ws-1",
            prompt="公路门户装货",
            expected_interface_id="highway",
            note="不要选铁路或水运装货",
        )
    )

    assert created.expected is not None
    assert created.expected.interface_id == "highway"
    assert created.expected.path == "/highway-api/portal/dispatchOrder/load"
    assert created.expected.title == "公路装货"
    assert created.expected.service == "c12-mtp"
    assert created.note == "不要选铁路或水运装货"


def test_delete_matches_clears_workspace_rows() -> None:
    service, _ = _service(_response([]))
    service.create_match(InterfacePromptMatchCreate(workspace_id="ws-1", prompt="装货"))
    assert service.delete_matches("ws-1") == 1
    assert service.list_matches("ws-1").items == []


def test_unknown_expected_interface_is_rejected() -> None:
    service, _ = _service(_response([]))
    try:
        service.create_match(
            InterfacePromptMatchCreate(
                workspace_id="ws-1",
                prompt="公路门户装货",
                expected_interface_id="missing",
            )
        )
    except InterfacePromptMatchError as exc:
        assert "正确接口" in str(exc)
    else:
        raise AssertionError("expected missing correct interface")


def test_client_judgment_looks_up_catalog_when_not_in_candidates() -> None:
    judgment = build_client_judgment(
        "codex",
        9,
        [
            _call(
                "read_forwarding_interface_detail",
                request_summary={"interface_id": "highway"},
                call_id=1,
            ),
        ],
        {},
        lookup=lambda interface_id: (
            InterfacePromptIdentity(
                interface_id="highway",
                method="POST",
                path="/highway-api/portal/dispatchOrder/load",
                title="公路装货",
            )
            if interface_id == "highway"
            else None
        ),
    )
    assert judgment.status == "selected"
    assert judgment.selected_path == "/highway-api/portal/dispatchOrder/load"
    assert judgment.in_candidates is False


def test_client_judgment_marks_execute_as_violated() -> None:
    judgment = build_client_judgment(
        "codex",
        9,
        [
            _call("search_forwarding_interfaces", call_id=1),
            _call("execute_forwarding_request", call_id=2),
        ],
        {},
    )
    assert judgment.status == "violated"
    assert judgment.prohibited_tool_calls == ["execute_forwarding_request"]
