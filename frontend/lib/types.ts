export type ProjectKind = "frontend" | "backend";
export type DatabaseEnvironment = string;
export type LegacyDatabaseEnvironment = "test" | "uat";
export type McpEnvironment = string;
export type DatabaseEnvironmentSelection =
  | "workspace_default"
  | "task_explicit";
export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };
export type EnvironmentJsonObject = Record<string, JsonValue>;

export interface McpEnvironmentOption {
  value: McpEnvironment;
  label: string;
}

export interface McpEnvironmentToolDefault {
  tool_name: string;
  title: string;
  description: string;
  environments: McpEnvironmentOption[];
  default_environment: McpEnvironment;
  source: "configured" | "built_in";
}

export interface WorkspaceMcpEnvironmentDefaults {
  workspace_id: string;
  tools: McpEnvironmentToolDefault[];
}

export interface WorkspaceEnvironmentOption {
  key: string;
  display_name: string;
  is_default: boolean;
  sort_order: number;
}

export interface WorkspaceEnvironmentList {
  workspace_id: string;
  default_environment: string;
  environments: WorkspaceEnvironmentOption[];
}

export interface NacosComponentRuleSummary {
  id: string;
  type: string;
  sources: Array<{ data_id: string; group: string }>;
  fields: Record<string, unknown>;
}

export interface NacosProfileSummary {
  workspace_id: string;
  profile_key: string;
  base_url: string;
  namespace_id: string;
  username: string;
  password_configured: boolean;
  request_timeout_ms: number;
  components: NacosComponentRuleSummary[];
  created_at: string | null;
  updated_at: string | null;
}

export interface WorkspaceNacosProfiles {
  workspace_id: string;
  profiles: NacosProfileSummary[];
}
export type SystemGuideDocument = Record<string, JsonValue>;

export interface SystemGuideDetail {
  id: string;
  document_id: string;
  guide_key: string;
  title: string;
  summary: string;
  document: SystemGuideDocument;
  include_in_prepare: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface SystemGuideWrite {
  guide_key: string;
  document: SystemGuideDocument;
  include_in_prepare: boolean;
  sort_order: number;
}

export interface ProjectSummary {
  id: string;
  name: string;
  project_kind: ProjectKind;
  project_type?: string;
  agents_path: string;
  document_relative_path: string;
  workspace_id?: string | null;
  workspace_name?: string | null;
  relative_path?: string | null;
  node_count: number;
  data_source_count?: number;
  database_count?: number;
  refreshed_at: string | null;
  error: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface WorkspaceSummary {
  id: string;
  name: string;
  workspace_type: string;
  root_path: string;
  project_count: number;
  error_project_count: number;
  data_source_count: number;
  database_count: number;
  database_authorization_count: number;
  document_reader_count: number;
  created_at?: string;
  updated_at: string;
}

export interface WorkspaceContainer {
  id: string;
  name: string;
  image: string;
  state: string;
  status: string;
  health: string | null;
  project_id: string | null;
  project_name: string | null;
  project_kind: ProjectKind | null;
  mode: string | null;
  operation_id: string | null;
  ports: string[];
}

export type WorkspaceContainerBulkAction = "restart" | "stop";

export interface WorkspaceContainerBulkActionResult {
  workspace_id: string;
  action: WorkspaceContainerBulkAction;
  project_kind: ProjectKind;
  target_count: number;
  succeeded_count: number;
  failed_count: number;
  failed_containers: string[];
}

export interface WorkspaceSharedFilesResult {
  workspace_id: string;
  source_root: string;
  document_count: number;
  deploy_count: number;
  action: "restore" | "publish";
}

export interface WorkspaceDataSourceAssignment {
  link_id: string;
  project_id: string;
  project_name: string;
  project_kind: ProjectKind;
  database_id: string;
  database_name: string;
  database_display_name: string;
  mcp_alias: string | null;
  alias: string;
  purpose: string;
  readonly: boolean;
  database_available: boolean;
  database_system: boolean;
  status: string;
}

export interface WorkspaceDataSourceUsage {
  id: string;
  name: string;
  category: string;
  engine: DatabaseEngine;
  database_count: number;
  assignment_count: number;
  project_count: number;
  assignments: WorkspaceDataSourceAssignment[];
}

export interface WorkspaceDataSourceSummary {
  workspace_id: string;
  source_count: number;
  database_count: number;
  assignment_count: number;
  project_count: number;
  sources: WorkspaceDataSourceUsage[];
}

export interface DatabaseEnvironmentTarget {
  link_id: string;
  database_id: string;
  database_name: string;
  database_display_name: string;
  namespace_type: "database" | "schema" | "file";
  data_source_id: string;
  data_source_name: string;
  engine: DatabaseEngine;
  available: boolean;
  readonly: boolean;
  system_database: boolean;
  mcp_alias?: string | null;
}

export interface DatabaseEnvironmentTargets {
  test: DatabaseEnvironmentTarget | null;
  uat: DatabaseEnvironmentTarget | null;
}

export interface WorkspaceDatabaseEnvironmentMapping {
  id: string | null;
  logical_name: string;
  mcp_alias: string;
  status: string;
  targets: DatabaseEnvironmentTargets;
  suggested_targets: DatabaseEnvironmentTargets;
  issues: string[];
}

export interface WorkspaceDatabaseEnvironmentProject {
  project_id: string;
  project_name: string;
  project_kind: ProjectKind;
  mappings: WorkspaceDatabaseEnvironmentMapping[];
  candidates: Record<LegacyDatabaseEnvironment, DatabaseEnvironmentTarget[]>;
}

export interface WorkspaceDatabaseEnvironmentSummary {
  mapping_count: number;
  complete_count: number;
  issue_count: number;
}

export interface WorkspaceDatabaseEnvironmentMappings {
  workspace_id: string;
  configured: boolean;
  active_environment: LegacyDatabaseEnvironment | null;
  revision: number;
  summary: WorkspaceDatabaseEnvironmentSummary;
  projects: WorkspaceDatabaseEnvironmentProject[];
}

export interface WorkspaceEnvironmentConfig {
  workspace_id: string;
  configured: boolean;
  active_environment: LegacyDatabaseEnvironment | null;
  revision: number;
  environments: Record<LegacyDatabaseEnvironment, EnvironmentJsonObject>;
  active_config: EnvironmentJsonObject | null;
}

export interface DocumentTreeNode {
  id: string;
  description: string;
  path: string;
  relative_path: string | null;
  error: string | null;
  project_id?: string | null;
  project_kind?: ProjectKind | null;
  selectable?: boolean;
  children: DocumentTreeNode[];
}

export interface DocumentDetail {
  id: string;
  description: string;
  path: string;
  relative_path: string | null;
  content: string;
  error: string | null;
}

export type DatabaseEngine =
  | "mysql"
  | "mariadb"
  | "doris"
  | "postgresql"
  | "sqlserver"
  | "sqlite"
  | "oracle"
  | "clickhouse";

export interface DataSourceSummary {
  id: string;
  name: string;
  category: string;
  engine: DatabaseEngine;
  description: string;
  connection_config: Record<string, string | number | boolean>;
  config_version: number;
  database_count: number;
  project_count: number;
  created_at: string;
  updated_at: string;
}

export interface DataSourcePasswordReveal {
  password: string;
}

export interface DataSourceEngineCapability {
  engine: DatabaseEngine;
  configurable: boolean;
  discoverable: boolean;
  searchable: boolean;
  queryable: boolean;
}

export interface DataSourceConnectionTestResult {
  engine: DatabaseEngine;
  status: "passed" | "failed";
  duration_ms: number;
  error_code?: string;
  message: string;
}

export interface DataSourceDatabaseSummary {
  id: string;
  data_source_id: string;
  remote_name: string;
  display_name: string;
  namespace_type: "database" | "schema" | "file";
  available: boolean;
  system_database: boolean;
  metadata: Record<string, string | number | boolean>;
  project_count: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectDatabaseLinkSummary {
  id: string;
  project_name: string;
  database_id: string;
  database_name: string;
  data_source_id: string;
  data_source_name: string;
  engine: DatabaseEngine;
  project_id: string;
  alias: string;
  mcp_alias?: string | null;
  purpose: string;
  readonly: boolean;
  allowed_schemas: string[];
  max_rows: number;
  max_result_bytes: number;
  query_timeout_ms: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectDatabaseOption {
  id: string;
  remote_name: string;
  display_name: string;
  namespace_type: "database" | "schema" | "file";
  available: boolean;
  selected: boolean;
  link_id: string | null;
  mcp_alias: string | null;
}

export interface ProjectDataSourceOption {
  id: string;
  name: string;
  category: string;
  engine: DatabaseEngine;
  databases: ProjectDatabaseOption[];
}

export interface ProjectDataSourceOptions {
  project_id: string;
  project_name: string;
  selected_source_count: number;
  selected_database_count: number;
  sources: ProjectDataSourceOption[];
}

export interface ContextDocumentNode {
  document_id: string;
  summary: string;
  children: ContextDocumentNode[];
}

export interface PreparedDatabase {
  database: string;
  engine: string;
  name: string;
  purpose: string;
  readonly: boolean;
  capabilities: string[];
  project_id?: string | null;
  project_name?: string | null;
  project_kind?: ProjectKind | null;
  environment?: DatabaseEnvironment | null;
}

export interface PreparedDatabaseEnvironment {
  key: DatabaseEnvironment;
  name: string;
  revision: number;
  selection: DatabaseEnvironmentSelection;
}

export interface PrepareTaskContextResult {
  task_id: number;
  documents: ContextDocumentNode;
  access: Array<
    "documents" | "database" | "environment" | "middleware" | "runtime"
  >;
  warnings?: string[];
}

export interface ContextTaskSummary {
  task_id: number;
  task: string;
  cwd: string;
  scope: "project" | "workspace";
  workspace_id?: string | null;
  workspace_name?: string | null;
  active_project_id?: string | null;
  active_project_name?: string | null;
  active_project_kind?: ProjectKind | null;
  database_environment?: DatabaseEnvironment | null;
  database_environment_revision?: number | null;
  database_environment_selection?: DatabaseEnvironmentSelection | null;
  agent_name?: string;
  created_at: string;
  read_call_count: number;
}

export interface ContextReadHistoryItem {
  position: number;
  document_id: string;
  path?: string;
  section?: string;
  status: "ok" | "error";
  error_code?: string;
}

export interface ContextReadHistoryCall {
  read_call_id: number;
  created_at: string;
  documents: ContextReadHistoryItem[];
}

export interface ContextDatabaseCallHistoryItem {
  database_call_id: number;
  operation: "search_objects" | "execute_query";
  database: string;
  engine: string;
  status: "ok" | "error";
  object_type?: string;
  statement_type?: string;
  duration_ms?: number;
  returned_count?: number;
  result_bytes?: number;
  truncated?: boolean;
  error_code?: string;
  created_at: string;
}

export interface ContextTaskReadHistory {
  task_id: number;
  task: string;
  project_name?: string;
  workspace_id?: string | null;
  workspace_name?: string | null;
  active_project_id?: string | null;
  active_project_name?: string | null;
  active_project_kind?: ProjectKind | null;
  scope: "project" | "workspace";
  database_environment?: DatabaseEnvironment | null;
  database_environment_revision?: number | null;
  database_environment_selection?: DatabaseEnvironmentSelection | null;
  agent_name?: string;
  created_at: string;
  calls: ContextReadHistoryCall[];
  database_calls: ContextDatabaseCallHistoryItem[];
}

export type McpTraceCallStatus =
  | "running"
  | "ok"
  | "error"
  | "cancelled";

export type McpTraceCompleteness = "complete" | "running" | "partial";

export type McpTraceCallSource =
  | "server"
  | "gateway"
  | "reported"
  | "legacy";

export type InternalMcpTraceCallSource = "server" | "legacy";

export type InternalMcpToolName =
  | "prepare_task_context"
  | "read_task_context"
  | "read_middleware_context"
  | "search_context_documents"
  | "read_context_document"
  | "search_database_objects"
  | "execute_database_query"
  | "apply_workspace_changes"
  | "start_workspace"
  | "get_workspace_operation"
  | "apply_project_changes"
  | "get_project_operation"
  | "prepare_table_relation_context";

export interface McpTraceDocumentArtifactItem {
  position: number;
  document_id: string;
  path?: string;
  section?: string;
  status: "ok" | "error";
  error_code?: string;
}

export interface McpTraceDocumentReadArtifact {
  kind: "document_read";
  read_call_id: number;
  documents: McpTraceDocumentArtifactItem[] | null;
}

export interface McpTraceDatabaseCallArtifact {
  kind: "database_call";
  database_call_id: number;
  operation: "search_objects" | "execute_query";
  database: string;
  engine: string;
  status: "ok" | "error";
  object_type?: string;
  statement_type?: string;
  returned_count?: number;
  result_bytes?: number;
  truncated?: boolean;
}

export interface McpTraceGenericArtifact {
  kind: string;
  [key: string]: unknown;
}

export type McpTraceArtifact =
  | McpTraceDocumentReadArtifact
  | McpTraceDatabaseCallArtifact
  | McpTraceGenericArtifact;

export interface McpTraceSummary {
  task_id: number;
  task: string;
  project_id?: string | null;
  project_name: string;
  cwd: string;
  agent_name?: string;
  created_at: string;
  call_count: number;
  error_count: number;
  server_names: string[];
  last_activity_at: string;
  trace_status: McpTraceCompleteness;
  warnings: string[];
}

export interface McpTraceToolCall {
  tool_call_id: number;
  sequence: number;
  parent_tool_call_id?: number | null;
  server_name: string;
  tool_name: string;
  source: McpTraceCallSource;
  status: McpTraceCallStatus;
  started_at: string;
  finished_at?: string | null;
  duration_ms?: number | null;
  request_summary?: Record<string, unknown> | null;
  result_summary?: Record<string, unknown> | null;
  database_payload_available?: boolean;
  database_payload_status?: McpDatabasePayloadStatus | null;
  database_payload_reason?: McpDatabasePayloadUnavailableReason | null;
  error_code?: string | null;
  artifacts: McpTraceArtifact[];
}

export type InternalMcpTraceToolCall = Omit<
  McpTraceToolCall,
  "source" | "tool_name"
> & {
  source: InternalMcpTraceCallSource;
  tool_name: InternalMcpToolName;
};

export interface McpTraceDetail extends McpTraceSummary {
  calls: McpTraceToolCall[];
}

export interface ChainFunnelMetrics {
  total_tasks: number;
  direct_hit_tasks: number;
  search_then_read_tasks: number;
  deep_search_tasks: number;
  direct_hit_rate: number;
  search_rate: number;
  avg_reads_per_task: number;
  avg_searches_per_task: number;
}

export interface DocumentHealthMatrixItem {
  document_id: string;
  document_path?: string | null;
  read_count: number;
  task_count: number;
  search_after_read_count: number;
  search_after_read_rate: number;
  health_category: "high_freq_effective" | "high_freq_ineffective" | "low_freq_effective" | "low_freq_ineffective" | string;
}

export interface BrokenLinkAlertItem {
  alert_type: "search_no_results" | "read_error" | "loop_search" | "deep_traversal" | string;
  task_id?: number | string;
  task_prompt?: string | null;
  agent_name?: string | null;
  message: string;
  created_at?: string;
}

export interface AgentComparisonItem {
  agent_name: string;
  total_tasks: number;
  avg_searches: number;
  avg_reads: number;
  direct_hit_rate: number;
}

export interface ChainAnalyticsOverview {
  funnel: ChainFunnelMetrics;
  health_matrix: DocumentHealthMatrixItem[];
  alerts: BrokenLinkAlertItem[];
  agent_comparison: AgentComparisonItem[];
}

export type McpDatabasePayloadStatus =
  | "pending"
  | "ok"
  | "error"
  | "cancelled"
  | "interrupted"
  | "capture_failed"
  | "expired";

export type McpDatabasePayloadUnavailableReason =
  | "not_captured"
  | "expired"
  | "capture_failed";

export interface McpDatabaseToolPayload {
  task_id: number;
  tool_call_id: number;
  tool_name: "search_database_objects" | "execute_database_query";
  available: boolean;
  reason?: McpDatabasePayloadUnavailableReason | null;
  status?: McpDatabasePayloadStatus | null;
  request_payload?: Record<string, unknown> | null;
  response_payload?: Record<string, unknown> | null;
  request_bytes?: number | null;
  response_bytes?: number | null;
  request_truncated: boolean;
  response_truncated: boolean;
  capture_error_code?: string | null;
  expires_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface McpServiceInfo {
  name: string;
  transport: string;
  url: string;
}

export interface McpToolInfo {
  name: string;
  description: string;
}

export interface McpToolsListResult {
  tools: Array<Record<string, JsonValue>>;
}

export interface McpClientConfig {
  client: "codex" | "antigravity";
  title: string;
  config_path: string;
  project_config_path?: string;
  config: string;
}

export interface McpIntegrationReadiness {
  database_configured: boolean;
  workspace_count: number;
  ready_for_full_test: boolean;
}

export interface McpIntegrationInfo {
  service: McpServiceInfo;
  tools: McpToolInfo[];
  clients: McpClientConfig[];
  readiness: McpIntegrationReadiness;
}

export interface McpIntegrationTestStage {
  key: string;
  label: string;
  status: "passed" | "failed" | "skipped";
  detail: string;
  duration_ms: number;
}

export interface McpIntegrationTestResult {
  status: "passed" | "failed";
  workspace_id: string;
  workspace_name?: string;
  task_id?: number;
  read_call_id?: number;
  started_at: string;
  finished_at: string;
  stages: McpIntegrationTestStage[];
}

export interface DocumentReadStatItem {
  document_id: string;
  document_path?: string | null;
  read_count: number;
  task_count: number;
  last_read_at: string;
}

export interface DocumentReadTaskItem {
  task_id: number;
  task: string;
  agent_name?: string | null;
  cwd: string;
  workspace_name?: string | null;
  active_project_name?: string | null;
  created_at: string;
  read_count: number;
  sections: string[];
}

export type TableRelationEnvironment = "test" | "uat";

export type TableRelationGenerationStatus =
  | "building"
  | "published"
  | "superseded"
  | "failed";

/**
 * `unknown` reaches the client rather than being filtered out: paired with the
 * evidence that produced it, "nobody could measure this" is an answer, and for
 * a domain that was never switched on it is the only honest one.
 */
export type TableRelationCardinality =
  | "one_to_one"
  | "one_to_many"
  | "many_to_one"
  | "unknown";

/** What the write paths permit. */
export type TableRelationCodeEvidence =
  | "enforced"
  | "single_write"
  | "batch_allowed"
  | "no_write_path"
  | "conflicted";

/** What the rows currently contain. */
export type TableRelationDbEvidence =
  | "measured"
  | "low_sample"
  | "never_written"
  | "no_data";

/** `self` is a column pointing at its own table, which is both ends at once. */
export type TableRelationDirection = "outbound" | "inbound" | "self";

/**
 * Whether a key is counted as a number or as a string. It decides how an unset
 * value is spelled — `0` or `''` — so the counts below cannot be read without it.
 */
export type TableRelationKeyKind = "numeric" | "text";

export interface TableRelationEndpoint {
  database_key: string;
  schema_name: string;
  table_name: string;
  column_name?: string | null;
}

/**
 * One row of the list. `relation_id` names the foreign key side and is the one
 * thing about a relation that does not change with the table you arrived from;
 * the two cardinalities do, because they are stated from that table's end.
 */
export interface TableRelationView {
  edge_id: string;
  relation_id: string;
  references: string;
  child: TableRelationEndpoint;
  parent: TableRelationEndpoint;
  direction: TableRelationDirection;
  code_cardinality: TableRelationCardinality;
  code_evidence: TableRelationCodeEvidence;
  db_cardinality: TableRelationCardinality;
  db_evidence: TableRelationDbEvidence;
  code_checked_at?: string | null;
  db_measured_at?: string | null;
  cross_database: boolean;
}

export interface TableRelationGenerationSummary {
  generation_id: string;
  revision: number;
  environment: TableRelationEnvironment;
  status: TableRelationGenerationStatus;
  edge_count: number;
  relation_count: number;
  hidden_count: number;
  published_at?: string | null;
}

export interface TableRelationStatus {
  workspace_id: string;
  generation?: TableRelationGenerationSummary | null;
  building?: TableRelationGenerationSummary | null;
  database_keys: string[];
  rebuild_command: string;
}

/** `hidden_count` is the dead columns held back from the list. */
export interface TableRelationTableSummary {
  database_key: string;
  schema_name: string;
  table_name: string;
  relation_count: number;
  hidden_count: number;
}

export interface TableRelationTableList {
  workspace_id: string;
  generation?: TableRelationGenerationSummary | null;
  only_related: boolean;
  total_count: number;
  related_count: number;
  returned_count: number;
  tables: TableRelationTableSummary[];
}

export interface TableRelationTableIdentity {
  database_key: string;
  schema_name: string;
  table_name: string;
}

export interface TableRelationTableDetail {
  workspace_id: string;
  generation: TableRelationGenerationSummary;
  table: TableRelationTableIdentity;
  relations: TableRelationView[];
  relation_count: number;
  /** Relations held back because the column has never been written. */
  hidden_count: number;
}

/**
 * The counts the data verdict was read off. Published so the verdict can be
 * recomputed and contradicted rather than only accepted.
 */
export interface TableRelationMeasurement {
  child_key_kind: TableRelationKeyKind;
  parent_key_kind: TableRelationKeyKind;
  child_table_rows: number;
  child_rows_with_value: number;
  child_distinct_keys: number;
  parent_rows_with_value: number;
  parent_distinct_keys: number;
  orphan_keys: number;
}

export type TableRelationCheckKey =
  | "cardinality"
  | "parent_unique"
  | "orphan"
  | "key_kind";

/**
 * `inconclusive` is not a milder `attention`: one says the check ran and found
 * nothing wrong, the other says there was nothing to run it against.
 */
export type TableRelationCheckOutcome =
  | "confirmed"
  | "attention"
  | "inconclusive";

export interface TableRelationCheck {
  key: TableRelationCheckKey;
  outcome: TableRelationCheckOutcome;
  /** Derived from the endpoints on read, so it cannot describe stale ones. */
  sql: string;
}

/**
 * What a place in the source is doing that decides how many children a parent key
 * gets. These name the deciding circumstance rather than the persistence call,
 * because the same `batchInsert` appears under `fresh_key_per_row` and under
 * `caller_key_reuse` — and reading the first as the second is how four relations
 * came to carry a wrong code verdict.
 */
export type TableRelationCodeSiteKind =
  | "fresh_key_per_row"
  | "caller_key_reuse"
  | "shared_key_fanout"
  | "single_write"
  | "unique_guard"
  | "strict_to_map"
  | "lossy_read"
  | "grouping_by";

/** A read cannot create a row, so it never settles a cardinality by itself. */
export type TableRelationSiteRole = "write" | "read";

/**
 * One place in the source a code verdict was read off. `role` and `implies` are
 * computed by the server from `kind`, so the client is never the thing deciding
 * whether a `groupingBy` writes rows.
 *
 * There is no line number on purpose: it is the one coordinate that would keep
 * looking exact after an edit moved the code. The method name and the snippet are
 * what a reader searches for, and a snippet no longer in the file is how staleness
 * becomes detectable rather than silent.
 */
export interface TableRelationCodeSite {
  kind: TableRelationCodeSiteKind;
  role: TableRelationSiteRole;
  implies: TableRelationCardinality;
  /** Relative to the workspace root. */
  file_path: string;
  method_name: string;
  snippet: string;
}

/**
 * One relation with the evidence behind both of its verdicts. `relation` is the
 * same view the list row was built from, so opening a row cannot show a verdict
 * that contradicts the row it was opened from.
 *
 * An empty `code_sites` is not the same as there being no write path: that is what
 * `code_evidence` says. Empty beside a conclusive evidence value means only that
 * nobody has written the places down yet.
 */
export interface TableRelationDetail {
  workspace_id: string;
  generation: TableRelationGenerationSummary;
  table: TableRelationTableIdentity;
  relation: TableRelationView;
  measurement: TableRelationMeasurement;
  checks: TableRelationCheck[];
  code_sites: TableRelationCodeSite[];
}

/**
 * How this table is persisted. Named after the call, not after the parent key:
 * relation code sites cannot reuse this vocabulary, because the same `batchInsert`
 * is 1:1 or 1:N depending on how the key is minted.
 */
export type TableRelationWriteKind =
  | "batch_insert"
  | "save_or_update"
  | "insert";

export type TableRelationUpdateKind =
  | "batch_update"
  | "save_or_update"
  | "update";

export type TableRelationPersistKind = TableRelationWriteKind | TableRelationUpdateKind;

export interface TableRelationWriteSite {
  kind: TableRelationWriteKind;
  /** Relative to the workspace root. */
  file_path: string;
  method_name: string;
  snippet: string;
}

/**
 * Insert calls recorded for one table. An empty `writes` is not a claim that
 * nothing inserts into the table — it means nobody has written the places down yet.
 */
export interface TableRelationTableWrites {
  workspace_id: string;
  generation: TableRelationGenerationSummary;
  table: TableRelationTableIdentity;
  writes: TableRelationWriteSite[];
}

export interface TableRelationUpdateSite {
  kind: TableRelationUpdateKind;
  file_path: string;
  method_name: string;
  snippet: string;
}

/**
 * Update calls recorded for one table. An empty `updates` is not a claim that
 * nothing updates the table — it means nobody has written the places down yet.
 */
export interface TableRelationTableUpdates {
  workspace_id: string;
  generation: TableRelationGenerationSummary;
  table: TableRelationTableIdentity;
  updates: TableRelationUpdateSite[];
}

/** What `read_table_relations` would return for one table, plus tool metadata. */
export interface TableRelationMcpPreview {
  tool: "read_table_relations";
  arguments: {
    task_id: string;
    tables: string[];
    database: string;
    sections?: string[];
    evidence?: "all";
  };
  result: {
    environment: DatabaseEnvironment;
    generation: {
      revision: number;
      generated_at: string | null;
    };
    workspace_root: string;
    tables: unknown[];
  };
}
