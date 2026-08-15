from __future__ import annotations

from pathlib import Path

import pytest

from context_router.services.sql_join_analyzer import (
    SqlObservedJoinAnalyzer,
    SqlSource,
)
from context_router.services.sql_preprocessing import (
    SqlPreprocessorConfig,
    SqlPreprocessorPipeline,
    SqlPreprocessorProfileError,
    SqlPreprocessorProfileLoader,
    SqlPreprocessProfile,
)


def profile(*processors: SqlPreprocessorConfig) -> SqlPreprocessProfile:
    return SqlPreprocessProfile(
        profile_id="workspace-template",
        profile_hash="a" * 64,
        project_patterns=("c12-*",),
        path_patterns=("**/*.sql",),
        dialects=("mysql",),
        processors=processors,
        max_candidates=12,
    )


def processor(name: str, **options: object) -> SqlPreprocessorConfig:
    return SqlPreprocessorConfig(processor_type=name, options=options)


@pytest.mark.parametrize(
    ("sql", "processors", "expected"),
    [
        (
            "<#-- comment --> SELECT * FROM cargo",
            (processor("freemarker_comments"),),
            "SELECT * FROM cargo",
        ),
        (
            "@pageTag() { SELECT * FROM cargo }",
            (processor("known_wrapper", names=["@pageTag"]),),
            "SELECT * FROM cargo",
        ),
        (
            "select @pageTag() { c.id, c.category_id @} from cargo c",
            (processor("known_wrapper", names=["@pageTag"]),),
            "select c.id, c.category_id from cargo c",
        ),
        (
            "SELECT * FROM cargo WHERE id = ${id}",
            (processor("value_placeholders"),),
            "SELECT * FROM cargo WHERE id = 0",
        ),
        (
            "SELECT * FROM cargo << AND status = :status >>",
            (processor("angle_conditionals"),),
            "SELECT * FROM cargo",
        ),
    ],
)
def test_safe_text_processors(
    sql: str,
    processors: tuple[SqlPreprocessorConfig, ...],
    expected: str,
) -> None:
    result = SqlPreprocessorPipeline().process(sql, profile(*processors))

    assert len(result.candidates) == 1
    assert " ".join(result.candidates[0].sql.split()) == expected
    assert result.candidates[0].template_derived is True


def test_conditionals_generate_include_and_exclude_candidates() -> None:
    result = SqlPreprocessorPipeline().process(
        "SELECT * FROM cargo c <#if includeCategory>"
        "LEFT JOIN category k ON c.category_id = k.id</#if>",
        profile(processor("freemarker_conditions")),
    )

    normalized = {" ".join(item.sql.split()) for item in result.candidates}
    assert normalized == {
        "SELECT * FROM cargo c LEFT JOIN category k ON c.category_id = k.id",
        "SELECT * FROM cargo c",
    }


def test_baseline_and_single_strategy_avoids_invalid_cartesian_clauses() -> None:
    result = SqlPreprocessorPipeline().process(
        "SELECT category_id, COUNT(*) FROM cargo GROUP BY category_id "
        "<#if first>HAVING COUNT(*) > 1</#if> "
        "<#if second>HAVING COUNT(*) < 10</#if>",
        profile(processor("freemarker_conditions", strategy="baseline_and_single")),
    )

    normalized = {" ".join(item.sql.split()) for item in result.candidates}
    assert normalized == {
        "SELECT category_id, COUNT(*) FROM cargo GROUP BY category_id",
        "SELECT category_id, COUNT(*) FROM cargo GROUP BY category_id HAVING COUNT(*) > 1",
        "SELECT category_id, COUNT(*) FROM cargo GROUP BY category_id HAVING COUNT(*) < 10",
    }
    assert all(statement.count("HAVING") <= 1 for statement in normalized)


def test_relation_only_conditions_ignore_filters_but_keep_conditional_joins() -> None:
    result = SqlPreprocessorPipeline().process(
        "SELECT * FROM cargo c "
        "<#if category?? && (category?size > 0)>"
        "JOIN category k ON c.category_id=k.id</#if> "
        "<#if keyword>WHERE c.name LIKE :keyword</#if>",
        profile(
            processor(
                "freemarker_conditions",
                strategy="baseline_and_single",
                relation_only=True,
            )
        ),
    )

    normalized = {" ".join(item.sql.split()) for item in result.candidates}
    assert normalized == {
        "SELECT * FROM cargo c",
        "SELECT * FROM cargo c JOIN category k ON c.category_id=k.id",
    }


def test_angle_conditionals_can_keep_the_canonical_relation_sql() -> None:
    result = SqlPreprocessorPipeline().process(
        "UPDATE cargo SET << status = :status >> WHERE << id = :id >>",
        profile(processor("angle_conditionals", mode="include")),
    )

    assert " ".join(result.candidates[0].sql.split()) == (
        "UPDATE cargo SET status = :status WHERE id = :id"
    )


def test_strict_value_placeholders_reject_structural_expressions() -> None:
    result = SqlPreprocessorPipeline().process(
        "SELECT * FROM cargo ORDER BY ${sortExpression}",
        profile(processor("value_placeholders", strict=True)),
    )

    assert result.candidates == ()
    assert [item.code for item in result.diagnostics] == ["template_expression_unsupported"]


def test_named_order_direction_only_replaces_allowlisted_order_placeholder() -> None:
    result = SqlPreprocessorPipeline().process(
        "SELECT * FROM cargo ORDER BY cargo.created_at :sortOrder",
        profile(processor("named_order_direction", names=["sortOrder"])),
    )

    assert " ".join(result.candidates[0].sql.split()) == (
        "SELECT * FROM cargo ORDER BY cargo.created_at ASC"
    )


def test_if_else_branches_are_never_concatenated() -> None:
    result = SqlPreprocessorPipeline().process(
        "SELECT * FROM cargo c <#if a>LEFT JOIN category k ON c.category_id=k.id"
        "<#else>LEFT JOIN owner o ON c.owner_id=o.id</#if>",
        profile(processor("freemarker_conditions")),
    )

    normalized = {" ".join(item.sql.split()) for item in result.candidates}
    assert len(normalized) == 2
    assert all(not ("category" in item and "owner" in item) for item in normalized)


@pytest.mark.parametrize("elseif_keyword", ["elseif", "elseIf"])
def test_if_elseif_else_branches_are_expanded_as_mutually_exclusive_candidates(
    elseif_keyword: str,
) -> None:
    result = SqlPreprocessorPipeline().process(
        "SELECT * FROM cargo c "
        "<#if category>LEFT JOIN category k ON c.category_id=k.id"
        f"<#{elseif_keyword} owner>LEFT JOIN owner o ON c.owner_id=o.id"
        "<#else>LEFT JOIN cargo_tag t ON c.id=t.cargo_id</#if>",
        profile(processor("freemarker_conditions")),
    )

    normalized = {" ".join(item.sql.split()) for item in result.candidates}
    assert normalized == {
        "SELECT * FROM cargo c LEFT JOIN category k ON c.category_id=k.id",
        "SELECT * FROM cargo c LEFT JOIN owner o ON c.owner_id=o.id",
        "SELECT * FROM cargo c LEFT JOIN cargo_tag t ON c.id=t.cargo_id",
    }
    assert result.diagnostics == ()


def test_baseline_and_single_keeps_static_joins_around_filter_only_elseif() -> None:
    result = SqlPreprocessorPipeline().process(
        "SELECT * FROM asn_header h "
        "LEFT JOIN asn_receive r ON h.asn_no=r.asn_code "
        "WHERE h.deleted=0 "
        "<#if inspection == '2'>AND r.status=2 "
        "<#elseIf inspection == '1'>AND (r.status=1 OR r.status IS NULL)</#if>",
        profile(
            processor(
                "freemarker_conditions",
                strategy="baseline_and_single",
                relation_only=True,
            )
        ),
    )

    normalized = {" ".join(item.sql.split()) for item in result.candidates}
    assert normalized == {
        "SELECT * FROM asn_header h LEFT JOIN asn_receive r ON h.asn_no=r.asn_code "
        "WHERE h.deleted=0"
    }
    assert result.diagnostics == ()


@pytest.mark.parametrize(
    "conditional",
    [
        "<#if a>x<#else>y<#else>z</#if>",
        "<#if a>x<#else>y<#elseif b>z</#if>",
    ],
)
def test_malformed_elseif_structure_fails_closed(conditional: str) -> None:
    result = SqlPreprocessorPipeline().process(
        f"SELECT * FROM cargo {conditional}",
        profile(processor("freemarker_conditions")),
    )

    assert result.candidates == ()
    assert [item.code for item in result.diagnostics] == ["template_block_unclosed"]


def test_nested_conditions_are_expanded_without_template_tokens() -> None:
    result = SqlPreprocessorPipeline().process(
        "SELECT * FROM cargo c <#if a><#if b>LEFT JOIN category k "
        "ON c.category_id=k.id</#if></#if>",
        profile(processor("freemarker_conditions")),
    )

    assert result.candidates
    assert all("<#" not in item.sql for item in result.candidates)


def test_unclosed_condition_fails_closed() -> None:
    result = SqlPreprocessorPipeline().process(
        "SELECT * FROM cargo <#if enabled> WHERE id=1",
        profile(processor("freemarker_conditions")),
    )

    assert result.candidates == ()
    assert [item.code for item in result.diagnostics] == ["template_block_unclosed"]


def test_loop_body_is_not_used_as_relation_evidence() -> None:
    result = SqlPreprocessorPipeline().process(
        "SELECT * FROM cargo c <#list tables as table>JOIN ${table} t ON c.id=t.id</#list>",
        profile(
            processor("freemarker_lists"),
            processor("dynamic_identifier_guard"),
            processor("value_placeholders"),
        ),
    )

    assert len(result.candidates) == 1
    assert "JOIN" not in result.candidates[0].sql
    assert [item.code for item in result.diagnostics] == ["template_loop_ignored"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM ${tableName}",
        "SELECT cargo_${columnName} FROM cargo",
        "SELECT * FROM cargo_${tenant}",
    ],
)
def test_dynamic_identifiers_fail_closed(sql: str) -> None:
    result = SqlPreprocessorPipeline().process(
        sql,
        profile(
            processor("dynamic_identifier_guard"),
            processor("value_placeholders"),
        ),
    )

    assert result.candidates == ()
    assert [item.code for item in result.diagnostics] == ["dynamic_identifier_unsupported"]


def test_unknown_directive_fails_closed() -> None:
    result = SqlPreprocessorPipeline().process(
        "<#assign table='cargo'> SELECT * FROM cargo",
        profile(processor("freemarker_comments")),
    )

    assert result.candidates == ()
    assert [item.code for item in result.diagnostics] == ["template_directive_unsupported"]


def test_profile_loader_matches_workspace_project_and_path(tmp_path: Path) -> None:
    config = tmp_path / "deploy/context-router/sql-preprocessors.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        """version: 1
defaults:
  max_candidates_per_file: 8
profiles:
  - id: cargo
    match:
      projects: [c12-mtp]
      paths: ['**/*.sql']
      exclude_paths: ['sql/**']
      dialects: [mysql]
    processors:
      - type: freemarker_comments
""",
        encoding="utf-8",
    )

    profiles = SqlPreprocessorProfileLoader().load(tmp_path)

    assert (
        profiles.match(
            project_name="c12-mtp",
            source_path="src/main/resources/cargo.sql",
            dialect="mysql",
        )
        is not None
    )
    assert (
        profiles.match(
            project_name="c12-wms",
            source_path="src/main/resources/cargo.sql",
            dialect="mysql",
        )
        is None
    )
    assert (
        profiles.match(
            project_name="c12-mtp",
            source_path="sql/20260101_init.sql",
            dialect="mysql",
        )
        is None
    )
    assert (
        profiles.excluded_by(
            project_name="c12-mtp",
            source_path="sql/20260101_init.sql",
            dialect="mysql",
        )
        is not None
    )


def test_missing_profile_file_preserves_default_behavior(tmp_path: Path) -> None:
    assert SqlPreprocessorProfileLoader().load(tmp_path).profiles == ()


@pytest.mark.parametrize(
    "content",
    [
        "version: 2\nprofiles: []\n",
        "version: 1\nprofiles: not-a-list\n",
        "version: 1\nprofiles:\n  - id: bad\n    processors:\n      - type: shell\n",
    ],
)
def test_invalid_profile_is_rejected(tmp_path: Path, content: str) -> None:
    config = tmp_path / "deploy/context-router/sql-preprocessors.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(content, encoding="utf-8")

    with pytest.raises(SqlPreprocessorProfileError):
        SqlPreprocessorProfileLoader().load(tmp_path)


class Metadata:
    def resolve_column(
        self,
        *,
        database_key: str,
        schema_name: str | None,
        table_name: str,
        column_name: str,
    ) -> tuple[str, str, str] | None:
        tables = {
            "cargo": {"id", "category_id"},
            "category": {"id"},
        }
        columns = tables.get(table_name.casefold(), set())
        if column_name.casefold() not in columns:
            return None
        return schema_name or "cargo_db", table_name, column_name


def test_analyzer_records_template_profile_on_safe_relation() -> None:
    selected_profile = profile(
        processor("freemarker_comments"),
        processor("freemarker_conditions"),
    )
    facts, warnings, statement_count = SqlObservedJoinAnalyzer().analyze(
        SqlSource(
            workspace_id="workspace-1",
            project_id="project-1",
            project_name="c12-mtp",
            database_key="cargo_db",
            dialect="mysql",
            source_path="src/main/resources/cargo.sql",
            statement=(
                "<#-- cargo --> SELECT * FROM cargo c <#if category>"
                "LEFT JOIN category k ON c.category_id=k.id</#if>"
            ),
        ),
        Metadata(),
        selected_profile,
    )

    assert statement_count == 2
    assert warnings == []
    assert len(facts) == 1
    assert facts[0].preprocess_profile_id == "workspace-template"
    assert facts[0].template_derived is True
    assert facts[0].applied_rules == (
        "freemarker_comments",
        "freemarker_conditions",
    )
