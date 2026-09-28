import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "evaluations/mtp-query-execution-v1"
SPEC = importlib.util.spec_from_file_location("mtp_validator", ROOT / "tools/validate_results.py")
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


@pytest.fixture
def result_file(tmp_path):
    batch = tmp_path / "batch-001"
    results = batch / "results"
    results.mkdir(parents=True)
    case = dict(case_id="mtp-read-0001", interface_id="a" * 36, method="POST", path="/query")
    (batch / "input.json").write_text(json.dumps({"cases": [case]}))
    case.update(
        status="completed",
        classification="non_empty_success",
        attempt_count=1,
        parameter_generation=dict(strategy="combined", confidence=1, evidence=[], assumptions=[]),
        request=dict(
            address_name=None, login_account_masked=None, role_name=None, path={}, query={}, body={}
        ),
        execution=None,
        error=None,
    )
    data = dict(
        schema_version="context-router-mtp-query-result-v1",
        campaign_id="panzhihua-mtp-test-query-2026-09",
        batch_id="batch-001",
        client="cursor",
        environment="test",
        case_count=1,
        cases=[case],
    )
    return results / "cursor.json", data


@pytest.mark.parametrize("mutation", ["valid", "strategy", "confidence", "extra", "hash", "root"])
def test_full_schema_validation(result_file, mutation):
    path, data = result_file
    data = copy.deepcopy(data)
    case = data["cases"][0]
    if mutation == "strategy":
        case["parameter_generation"]["strategy"] = "database_query"
    elif mutation == "confidence":
        case["parameter_generation"]["confidence"] = 2
    elif mutation == "extra":
        case["unexpected"] = "secret-must-not-appear"
    elif mutation == "hash":
        case["execution"] = {"response_sha256": "invalid"}
    elif mutation == "root":
        data = []
    path.write_text(json.dumps(data))
    errors, _ = validator.validate(path)
    assert bool(errors) == (mutation != "valid")
    assert "secret-must-not-appear" not in str(errors)


@pytest.mark.parametrize(
    "body,valid",
    [([], True), ([1, 2], True), ({}, True), (None, True), ("invalid", False), (1, False)],
)
def test_request_body_shape(result_file, body, valid):
    path, data = result_file
    data["cases"][0]["request"]["body"] = body
    path.write_text(json.dumps(data))
    errors, _ = validator.validate(path)
    assert (not errors) == valid
