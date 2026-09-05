from context_router.services.interface_forwarding import InterfaceForwardingService


class _OverviewCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, statement: str, params: tuple[str, ...]) -> None:
        assert statement.count("%s") == len(params)
        self.calls.append((statement, params))

    @staticmethod
    def fetchall() -> list[dict[str, object]]:
        return []


class _OverviewConnection:
    def __init__(self, cursor: _OverviewCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def cursor(self) -> _OverviewCursor:
        return self._cursor


def test_overview_binds_every_filter_placeholder_for_empty_and_non_empty_keywords(
    monkeypatch,
) -> None:
    service = InterfaceForwardingService("postgresql://unused")
    cursor = _OverviewCursor()
    connection = _OverviewConnection(cursor)
    monkeypatch.setattr(service, "_connect", lambda: connection)
    monkeypatch.setattr(service, "list_environments", lambda *_args, **_kwargs: [])

    service.overview("workspace-1")
    service.overview("workspace-1", "司机")

    interface_calls = [params for statement, params in cursor.calls if "semantic.search_document" in statement]
    assert interface_calls == [
        ("workspace-1", "", "%%", "%%", "%%", "%%", "%%"),
        ("workspace-1", "司机", "%司机%", "%司机%", "%司机%", "%司机%", "%司机%"),
    ]


def test_source_identity_is_not_rewritten_by_workspace_business_rules() -> None:
    assert (
        InterfaceForwardingService._coalesce_interface_name(
            "getDriverPage",
            operation_id="driverPage",
            method="GET",
            path="/api/drivers",
        )
        == "getDriverPage"
    )


def test_controller_name_is_derived_generically_from_openapi_tag() -> None:
    assert (
        InterfaceForwardingService._controller_name(
            {"tags": ["inventory-report-controller"]}
        )
        == "InventoryReportController"
    )


def test_openapi_result_does_not_contain_retired_semantic_fields() -> None:
    endpoint = InterfaceForwardingService._parse_spec(
        {
            "openapi": "3.0.0",
            "paths": {
                "/widgets": {
                    "post": {
                        "tags": ["widget-controller"],
                        "summary": "Create widget",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
    )[0]

    assert endpoint["controller_name"] == "WidgetController"
    assert "crud_type" not in endpoint
    assert "controller_description" not in endpoint
