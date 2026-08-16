from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TableRelationDetailLevel = Literal["compact", "evidence", "full"]
TableRelationWarningDisposition = Literal["attention", "expected"]
TableRelationAutomaticWhitelistGroup = Literal["no_value", "parser_gap"]
TableRelationAutomaticWhitelistRuleCode = Literal[
    "automatic_ddl",
    "automatic_single_table_query",
    "automatic_write_without_query",
    "automatic_single_table_initialization",
    "automatic_missing_table_or_column",
    "automatic_invalid_sql",
    "automatic_complex_sql",
    "automatic_derived_relation",
    "automatic_or_unsupported",
    "automatic_non_equality",
    "automatic_correlated_reference",
]


class TableIdentity(BaseModel):
    project_id: str
    project_name: str
    database_key: str
    schema_name: str
    table_name: str


class TableJoinColumnPair(BaseModel):
    column_a: str
    column_b: str


class TableJoinEvidence(BaseModel):
    source_kind: Literal["sql_file"] = "sql_file"
    source_path: str
    join_expression: str
    sql_statement: str | None = None
    preprocess_profile_id: str | None = None
    preprocess_profile_hash: str | None = None
    preprocess_candidate_id: str | None = None
    applied_rules: list[str] = Field(default_factory=list)
    template_derived: bool = False


class ObservedTableJoin(BaseModel):
    relation_id: str
    relation_kind: Literal["observed_join"] = "observed_join"
    directed: Literal[False] = False
    table_a: TableIdentity
    table_b: TableIdentity
    column_pairs: list[TableJoinColumnPair]
    statement_count: int = Field(ge=1)
    source_file_count: int = Field(ge=1)
    evidence_total: int = Field(ge=0)
    evidence_returned: int = Field(ge=0)
    evidence_truncated: bool
    evidence: list[TableJoinEvidence] = Field(default_factory=list)


class TableRelationSemantics(BaseModel):
    kind: Literal["observed_sql_join"] = "observed_sql_join"
    directed: Literal[False] = False
    notice: str = "结果表示项目 SQL 中观察到的字段等值关联，不等同于外键、主从关系或数据血缘。"


class TableRelationDatabaseScope(BaseModel):
    source: Literal["workspace_default"] = "workspace_default"
    environment_independent: Literal[True] = True
    config_revision: int = Field(ge=1)
    database_key: str
    schema_name: str


class TableRelationContextResult(BaseModel):
    workspace_id: str
    task_id: int | None = None
    detail_level: TableRelationDetailLevel
    relation_semantics: TableRelationSemantics = Field(default_factory=TableRelationSemantics)
    relation_database_scope: TableRelationDatabaseScope
    root_table: TableIdentity
    related_tables: list[TableIdentity]
    joins: list[ObservedTableJoin]
    total_relation_count: int = Field(ge=0)
    returned_relation_count: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(default=None, ge=0)
    warnings: list[str] = Field(default_factory=list)


class TableRelationTableOption(TableIdentity):
    relation_count: int = Field(ge=0)


class TableRelationTableList(BaseModel):
    workspace_id: str
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(default=None, ge=0)
    tables: list[TableRelationTableOption]


class TableRelationProjectBuildStatus(BaseModel):
    project_id: str
    project_name: str
    database_key: str | None = None
    status: Literal["missing", "building", "ready", "failed"]
    sql_file_count: int = Field(ge=0)
    statement_count: int = Field(ge=0)
    relation_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    attention_warning_count: int = Field(default=0, ge=0)
    expected_skip_count: int = Field(default=0, ge=0)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TableRelationBuildStatus(BaseModel):
    workspace_id: str
    status: Literal["missing", "building", "ready", "partial", "failed"]
    generation_id: str | None = None
    project_count: int = Field(ge=0)
    ready_project_count: int = Field(ge=0)
    sql_file_count: int = Field(ge=0)
    statement_count: int = Field(ge=0)
    relation_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    attention_warning_count: int = Field(default=0, ge=0)
    expected_skip_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    config_revision: int = Field(ge=0)
    eligible_project_count: int = Field(ge=0)
    configured_project_count: int = Field(ge=0)
    projects: list[TableRelationProjectBuildStatus] = Field(default_factory=list)


class TableRelationWarningCategory(BaseModel):
    code: str
    label: str
    classification: Literal["source_error", "preprocessor", "metadata", "relation_gap", "safe_skip"]
    disposition: TableRelationWarningDisposition
    count: int = Field(ge=0)


class TableRelationWarningItem(BaseModel):
    project_id: str
    project_name: str
    database_key: str
    source_path: str
    code: str
    category: str
    classification: Literal["source_error", "preprocessor", "metadata", "relation_gap", "safe_skip"]
    disposition: TableRelationWarningDisposition
    message: str
    expression: str | None = None
    occurrence_count: int = Field(ge=1)


class TableRelationWarningProjectSummary(BaseModel):
    project_id: str
    project_name: str
    database_key: str
    count: int = Field(ge=0)


class TableRelationWarningList(BaseModel):
    workspace_id: str
    total: int = Field(ge=0)
    attention_total: int = Field(ge=0)
    expected_total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    categories: list[TableRelationWarningCategory]
    projects: list[TableRelationWarningProjectSummary]
    warnings: list[TableRelationWarningItem]


class TableRelationSqlWhitelistRule(BaseModel):
    code: TableRelationAutomaticWhitelistRuleCode
    group: TableRelationAutomaticWhitelistGroup
    label: str
    description: str


class TableRelationSqlWhitelistConfiguration(BaseModel):
    workspace_id: str
    project_id: str
    project_name: str
    paths: list[str]
    suggested_paths: list[str]
    automatic_rules: list[TableRelationSqlWhitelistRule]


class TableRelationSqlWhitelistUpdate(BaseModel):
    paths: list[str] = Field(default_factory=list, max_length=1000)


class TableRelationAutomaticWhitelistFile(BaseModel):
    project_id: str
    project_name: str
    source_path: str
    statement_bytes: int = Field(ge=0)


class TableRelationAutomaticWhitelistFileList(BaseModel):
    workspace_id: str
    project_id: str | None = None
    project_name: str | None = None
    rule: TableRelationSqlWhitelistRule
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(default=None, ge=0)
    files: list[TableRelationAutomaticWhitelistFile]


class TableRelationAutomaticWhitelistFileContent(BaseModel):
    workspace_id: str
    project_id: str
    project_name: str
    rule: TableRelationSqlWhitelistRule
    source_path: str
    statement: str
    truncated: bool = False


class TableRelationDefaultDatabaseOption(BaseModel):
    project_database_id: str
    database_key: str
    schema_name: str
    data_source_name: str
    display_name: str
    selected: bool


class TableRelationDefaultDatabaseProject(BaseModel):
    project_id: str
    project_name: str
    selected_project_database_id: str | None = None
    options: list[TableRelationDefaultDatabaseOption]


class TableRelationDefaultDatabaseConfiguration(BaseModel):
    workspace_id: str
    revision: int = Field(ge=0)
    configured: bool
    eligible_project_count: int = Field(ge=0)
    configured_project_count: int = Field(ge=0)
    projects: list[TableRelationDefaultDatabaseProject]


class TableRelationDefaultDatabaseSelection(BaseModel):
    project_id: str = Field(min_length=1, max_length=32)
    project_database_id: str = Field(min_length=1, max_length=32)


class TableRelationDefaultDatabaseUpdate(BaseModel):
    expected_revision: int = Field(ge=0)
    defaults: list[TableRelationDefaultDatabaseSelection] = Field(min_length=1, max_length=200)
