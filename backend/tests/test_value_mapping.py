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


def _service() -> ValueMappingService:
    return ValueMappingService(
        database_url=None,
        database_access_service=object(),  # type: ignore[arg-type]
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
    assert len(result["bindings"]) == 20
    assert result["bindings_truncated"] is True


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
