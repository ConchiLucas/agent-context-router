from context_router.services.interface_response_validation import InterfaceResponseValidator


def test_response_validation_detects_business_failure_on_http_200() -> None:
    result = InterfaceResponseValidator.validate(
        status_code=200,
        response_body='{"code":500,"message":"failed"}',
        response_schema={"type": "object", "properties": {"code": {"type": "integer"}}},
        response_rule={},
        response_truncated=False,
        error_type=None,
    )

    assert result["status"] == "failed"
    assert result["failure_checks"] == ["business"]


def test_response_validation_uses_configured_success_path() -> None:
    result = InterfaceResponseValidator.validate(
        status_code=200,
        response_body='{"meta":{"status":"SUCCESS"},"data":[]}',
        response_schema={
            "type": "object",
            "required": ["data"],
            "properties": {"data": {"type": "array"}},
        },
        response_rule={
            "success_code_paths": ["meta.status"],
            "success_values": ["SUCCESS"],
        },
        response_truncated=False,
        error_type=None,
    )

    assert result["status"] == "passed"
    assert result["checks"]["business"]["status"] == "passed"  # type: ignore[index]


def test_response_validation_warns_when_contract_is_not_configured() -> None:
    result = InterfaceResponseValidator.validate(
        status_code=204,
        response_body="",
        response_schema={},
        response_rule={},
        response_truncated=False,
        error_type=None,
    )

    assert result["status"] == "warning"
