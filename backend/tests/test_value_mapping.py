from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from context_router.schemas.value_mapping import ValueMappingWrite
from context_router.services.value_mapping import ValueMappingError, ValueMappingService


class _TaskRepository:
    def get_task(self, _task_id: int) -> SimpleNamespace:
        return SimpleNamespace(
            scope="workspace",
            workspace_id="workspace-1",
            database_environment="uat",
        )


def _service(database_access: object | None = None) -> ValueMappingService:
    return ValueMappingService(
        database_url=None,
        database_access_service=database_access or object(),  # type: ignore[arg-type]
        connector_manager=object(),  # type: ignore[arg-type]
        sql_policy=object(),  # type: ignore[arg-type]
        task_repository=_TaskRepository(),  # type: ignore[arg-type]
    )


def _mapping() -> dict[str, object]:
    return {
        "table_name": "member_shipper",
        "schema_name": None,
        "value_column": "id",
        "search_columns": ["shipper_name", "mobile"],
        "display_columns": ["shipper_name"],
        "filters": {"status": 1},
    }


def test_preview_sql_is_bounded_and_escapes_literals() -> None:
    sql = ValueMappingService._preview_sql(
        _mapping(),
        engine="mysql",
        keyword="O'Reilly",
        limit=200,
    )

    assert "FROM `member_shipper`" in sql
    assert "CONCAT('%', 'O''Reilly', '%')" in sql
    assert "`status` = 1" in sql
    assert sql.endswith("LIMIT 20")


def test_preview_sql_rejects_invalid_identifiers() -> None:
    mapping = _mapping()
    mapping["table_name"] = "member_shipper; DROP TABLE users"

    with pytest.raises(ValueMappingError, match="无效数据库标识符"):
        ValueMappingService._preview_sql(
            mapping,
            engine="postgresql",
            keyword="",
            limit=10,
        )


def test_mcp_scope_inherits_task_environment_and_rejects_override() -> None:
    service = _service()

    assert service._task_scope(9) == ("workspace-1", "uat")
    assert service._task_scope(9, "UAT") == ("workspace-1", "uat")
    with pytest.raises(ValueMappingError, match="显式环境与任务环境不一致") as exc_info:
        service._task_scope(9, "local")

    assert exc_info.value.code == "environment_mismatch"


def test_mapping_source_resolves_empty_schema_from_task_environment_database() -> None:
    class DatabaseAccess:
        def resolve(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(
                policy=SimpleNamespace(
                    allowed_schemas=(),
                    engine="mysql",
                    current_database="uat_mtp",
                )
            )

    service = _service(DatabaseAccess())
    service.get = lambda _mapping_id: {  # type: ignore[method-assign]
        "workspace_id": "workspace-1",
        "status": "published",
        "database_alias": "c12_mtp_db",
        "schema_name": None,
        "table_name": "cs_dsly_highway_carrier_order",
        "value_column": "carrier_order_no",
    }

    source = service.source_for_task("mapping-1", task_id=9)

    assert source["environment"] == "uat"
    assert source["schema_name"] == "uat_mtp"
    assert source["schema_source"] == "environment_database_namespace"


def test_mapping_source_rejects_ambiguous_empty_postgres_schema() -> None:
    class DatabaseAccess:
        def resolve(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(
                policy=SimpleNamespace(
                    allowed_schemas=("public", "archive"),
                    engine="postgresql",
                    current_database="uat_mtp",
                )
            )

    service = _service(DatabaseAccess())
    service.get = lambda _mapping_id: {  # type: ignore[method-assign]
        "workspace_id": "workspace-1",
        "status": "published",
        "database_alias": "c12_mtp_db",
        "schema_name": None,
        "table_name": "orders",
        "value_column": "id",
    }

    with pytest.raises(ValueMappingError, match="不能唯一确定真实 Schema") as exc_info:
        service.source_for_task("mapping-1", task_id=9)

    assert exc_info.value.code == "mapping_schema_unresolved"


def test_mcp_mapping_filters_exact_interface_parameter_and_bounds_bindings() -> None:
    bindings = [
        {
            "interface_id": "interface-1" if index < 21 else "interface-2",
            "location": "body",
            "parameter_path": "shipperId",
        }
        for index in range(22)
    ]
    mapping = {
        "id": "mapping-1",
        "value_key": "shipper_id",
        "name": "货主ID",
        "description": "货主主键",
        "aliases": ["货主编号"],
        "resolver_type": "database_column",
        "database_alias": "member",
        "schema_name": None,
        "table_name": "member_shipper",
        "value_column": "id",
        "search_columns": ["shipper_name"],
        "display_columns": ["shipper_name"],
        "filters": {"status": 1},
        "bindings": bindings,
    }

    result = ValueMappingService._mcp_mapping(
        mapping,
        interface_id="interface-1",
        location="body",
        parameter_path="shipperId",
    )

    assert result["binding_count"] == 21
    assert result["bindings_included"] is True
    assert len(result["bindings"]) == 20
    assert result["bindings_truncated"] is True


def test_mcp_mapping_omits_binding_details_without_interface_scope() -> None:
    mapping = {
        "id": "mapping-1",
        "value_key": "shipper_id",
        "name": "货主ID",
        "description": "货主主键",
        "aliases": ["货主编号"],
        "resolver_type": "database_column",
        "database_alias": "member",
        "schema_name": None,
        "table_name": "member_shipper",
        "value_column": "id",
        "search_columns": ["shipper_name"],
        "display_columns": ["shipper_name"],
        "filters": {"status": 1},
        "bindings": [{"interface_id": f"interface-{index}"} for index in range(3)],
    }

    result = ValueMappingService._mcp_mapping(
        mapping,
        interface_id=None,
        location=None,
        parameter_path=None,
    )

    assert result["binding_count"] == 3
    assert result["bindings_included"] is False
    assert result["bindings"] == []
    assert result["bindings_truncated"] is True


def test_candidate_selection_preserves_default_order_and_bounds_random_pool() -> None:
    candidates = [{"value": index} for index in range(10)]

    assert (
        ValueMappingService._select_candidates(
            candidates,
            selection="default",
            limit=2,
        )
        == candidates[:2]
    )
    selected = ValueMappingService._select_candidates(
        candidates,
        selection="random",
        limit=3,
    )

    assert len(selected) == 3
    assert all(item in candidates for item in selected)
    assert len({item["value"] for item in selected}) == 3


def test_interface_parameters_include_nested_body_fields_and_path_fallback() -> None:
    parameters = ValueMappingService._parameters(
        {
            "query": {
                "type": "object",
                "properties": {"pageNumber": {"type": "integer"}},
            },
            "body": {
                "type": "object",
                "required": ["shipper"],
                "properties": {
                    "shipper": {
                        "type": "object",
                        "required": ["id"],
                        "properties": {"id": {"type": "string", "description": "货主 ID"}},
                    },
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"goodsId": {"type": "string"}},
                        },
                    },
                },
            },
        },
        "/orders/{orderId}",
    )

    by_path = {(item["location"], item["parameter_path"]): item for item in parameters}
    assert by_path[("query", "pageNumber")]["type"] == "integer"
    assert by_path[("body", "shipper.id")]["required"] is True
    assert by_path[("body", "shipper.id")]["description"] == "货主 ID"
    assert by_path[("body", "items[].goodsId")]["required"] is False
    assert by_path[("path", "orderId")]["required"] is True


def test_write_schema_normalizes_aliases_and_rejects_invalid_value_key() -> None:
    payload = ValueMappingWrite(
        workspace_id="workspace-1",
        value_key="shipper_id",
        name=" 货主 ID ",
        database_alias=" MTP ",
        table_name=" member_shipper ",
        value_column=" id ",
        aliases=["货主编号", " 货主编号 ", "托运人 ID"],
    )

    assert payload.name == "货主 ID"
    assert payload.aliases == ["货主编号", "托运人 ID"]

    with pytest.raises(ValidationError):
        ValueMappingWrite(
            workspace_id="workspace-1",
            value_key="Shipper-ID",
            name="货主 ID",
            database_alias="mtp",
            table_name="member_shipper",
            value_column="id",
        )
