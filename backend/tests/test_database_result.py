import ipaddress
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from context_router.database import (
    Column,
    DatabaseObject,
    DatabaseResultFormatter,
    EffectiveQueryPolicy,
    QueryResult,
    ResultFormattingError,
    SearchObjectsResult,
    TruncationReason,
    compact_json_bytes,
    normalize_json_value,
)


def make_policy(*, max_rows: int = 1_000, max_result_bytes: int = 2_000_000):
    return EffectiveQueryPolicy(
        engine="clickhouse",
        current_database="analytics",
        readonly=True,
        allowed_schemas=(),
        max_rows=max_rows,
        max_result_bytes=max_result_bytes,
        query_timeout_ms=15_000,
    )


def test_json_normalization_covers_database_scalar_and_complex_types() -> None:
    value = {
        "safe": (1 << 53) - 1,
        "large": 1 << 64,
        "decimal": Decimal("12.3400"),
        "date": date(2026, 7, 22),
        "datetime": datetime(2026, 7, 22, 8, 30, tzinfo=UTC),
        "uuid": UUID("12345678-1234-5678-1234-567812345678"),
        "ipv4": ipaddress.ip_address("127.0.0.1"),
        "ipv6": ipaddress.ip_address("2001:db8::1"),
        "bytes": b"\x00\xff",
        "array": [None, (2, 3)],
        "nan": float("nan"),
        "positive_infinity": float("inf"),
        "negative_infinity": float("-inf"),
    }

    normalized = normalize_json_value(value)

    assert normalized["safe"] == (1 << 53) - 1
    assert normalized["large"] == str(1 << 64)
    assert normalized["decimal"] == "12.3400"
    assert normalized["date"] == "2026-07-22"
    assert normalized["datetime"] == "2026-07-22T08:30:00+00:00"
    assert normalized["uuid"] == "12345678-1234-5678-1234-567812345678"
    assert normalized["ipv4"] == "127.0.0.1"
    assert normalized["ipv6"] == "2001:db8::1"
    assert normalized["bytes"] == "AP8="
    assert normalized["array"] == [None, [2, 3]]
    assert normalized["nan"] == "NaN"
    assert normalized["positive_infinity"] == "Infinity"
    assert normalized["negative_infinity"] == "-Infinity"


def test_query_formatter_preserves_duplicate_columns_and_truncates_by_rows() -> None:
    formatter = DatabaseResultFormatter()
    raw = QueryResult(
        columns=[Column("value", "UInt64"), Column("value", "String")],
        rows=((index, f"row-{index}") for index in range(4)),
        elapsed_ms=7,
    )

    result = formatter.format_query(raw, make_policy(max_rows=2))

    assert result.columns[0]["name"] == "value"
    assert result.columns[1]["name"] == "value"
    assert result.rows == ((0, "row-0"), (1, "row-1"))
    assert result.returned_rows == 2
    assert result.truncated is True
    assert result.truncation_reason == TruncationReason.ROWS
    assert result.result_bytes == len(compact_json_bytes(result.as_dict()))


def test_query_formatter_counts_utf8_bytes_and_envelope() -> None:
    formatter = DatabaseResultFormatter()
    envelope = {"task_id": 42, "database": "分析库", "engine": "clickhouse"}
    baseline = formatter.format_query(
        QueryResult(columns=[Column("内容", "String")], rows=[]),
        make_policy(),
        envelope=envelope,
    )
    budget = baseline.result_bytes + 60
    raw = QueryResult(
        columns=[Column("内容", "String")],
        rows=[("中文🙂" * 3,), ("继续🙂" * 3,)],
    )

    result = formatter.format_query(
        raw,
        make_policy(max_result_bytes=budget),
        envelope=envelope,
    )
    final_payload = {**envelope, **result.as_dict()}

    assert result.result_bytes == len(compact_json_bytes(final_payload))
    assert result.result_bytes <= budget
    assert result.truncated is True
    assert result.truncation_reason == TruncationReason.BYTES


def test_query_formatter_rejects_one_oversized_cell() -> None:
    formatter = DatabaseResultFormatter()

    with pytest.raises(ResultFormattingError) as oversized:
        formatter.format_query(
            QueryResult(columns=[Column("value", "String")], rows=[("x" * 1_000,)]),
            make_policy(max_result_bytes=250),
        )

    assert oversized.value.code == "result_cell_too_large"


def test_query_formatter_rejects_oversized_column_metadata() -> None:
    formatter = DatabaseResultFormatter()

    with pytest.raises(ResultFormattingError) as oversized:
        formatter.format_query(
            QueryResult(columns=[Column("x" * 1_000, "String")], rows=[]),
            make_policy(max_result_bytes=250),
        )

    assert oversized.value.code == "result_metadata_too_large"


def test_search_formatter_applies_object_and_byte_limits() -> None:
    formatter = DatabaseResultFormatter()
    raw = SearchObjectsResult(
        objects=(
            DatabaseObject(name=f"event_{index}", schema="analytics", kind="table")
            for index in range(4)
        ),
        elapsed_ms=3,
    )

    result = formatter.format_search(raw, max_objects=2, max_result_bytes=10_000)

    assert result.returned_count == 2
    assert result.truncated is True
    assert result.truncation_reason == TruncationReason.OBJECTS
    assert result.result_bytes == len(compact_json_bytes(result.as_dict()))


def test_json_normalization_rejects_cycles() -> None:
    value: list[object] = []
    value.append(value)

    with pytest.raises(ResultFormattingError) as cyclic:
        normalize_json_value(value)

    assert cyclic.value.code == "query_failed"
