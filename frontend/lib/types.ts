export type ProjectKind = "frontend" | "backend";

export interface SharedAiProvider {
  id: string;
  label: string;
  type: string;
  base_url: string;
  api_key: string;
  model: string;
  max_tokens: number;
  voice: string;
  capabilities: string[];
  options: Record<string, unknown>;
  enabled: boolean;
  active: boolean;
}

export interface SharedAiCatalog {
  configured_default_provider_id: string;
  center_active_provider_id: string;
  active_provider_id: string;
  default_source: string;
  default_recovered: boolean;
  notice: string | null;
  revision: number;
  providers: SharedAiProvider[];
}

export interface SharedDatabaseConnection {
  id: string;
  name: string;
  type: string;
  environment: string;
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  parameters: Record<string, string>;
}

export interface SharedLocalCliItem {
  id: string;
  label: string;
  enabled: boolean;
  command: string;
  default_args: string[];
  model: string;
  reasoning_effort: string;
  working_directory: string;
  timeout_seconds: number;
  capabilities: string[];
  active: boolean;
}

export interface SharedLocalCliConfiguration {
  active_config_id: string;
  configs: SharedLocalCliItem[];
}

export interface SharedObjectStorageConfiguration {
  configured: boolean;
  enabled: boolean;
  endpoint: string;
  access_key_id: string;
  secret_access_key: string;
  use_ssl: boolean;
  bucket_name: string;
  base_path: string;
}

export interface SharedImageModelCatalog {
  active_provider_id: string;
  providers: SharedAiProvider[];
}

export interface SharedConfigurationCatalog {
  ai: SharedAiCatalog;
  databases: SharedDatabaseConnection[];
  local_cli: SharedLocalCliConfiguration;
  object_storage: SharedObjectStorageConfiguration;
  image_models: SharedImageModelCatalog;
  runtime: Record<string, unknown>;
}
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
  aliases: string[];
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
  execution_contract: {
    intent_type: AiTaskIntentType;
    error_signal: boolean;
    intent_summary?: string | null;
    intent_source: AiTaskIntentSource;
    mutation_policy: "allowed" | "forbidden";
    required_steps: string[];
    visualization_targets: Array<"task" | "data" | "interface" | "log">;
    instructions: string[];
  };
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
  intent_type?: AiTaskIntentType;
  intent_error_signal?: boolean;
  intent_summary?: string | null;
  intent_source?: AiTaskIntentSource;
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
  intent_type?: AiTaskIntentType;
  intent_error_signal?: boolean;
  intent_summary?: string | null;
  intent_source?: AiTaskIntentSource;
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
  | "resolve_database_target"
  | "search_database_objects"
  | "execute_database_query"
  | "save_data_visualization_query"
  | "execute_mapped_data_query"
  | "save_task_visualization_result"
  | "list_task_containers"
  | "inspect_container_errors"
  | "read_table_relations"
  | "search_relation_tables"
  | "search_value_mappings"
  | "resolve_value_candidates"
  | "search_forwarding_interfaces"
  | "read_forwarding_request_history"
  | "prepare_forwarding_request"
  | "execute_forwarding_request"
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
  client: "codex" | "gemini" | "antigravity" | "cursor" | "grok";
  title: string;
  config_path: string;
  project_config_path?: string;
  setup_kind: "file" | "command";
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

export type TableRelationEnvironment = string;

export interface RelationRecordTable {
  database_key: string;
  schema_name: string;
  table_name: string;
}

export interface RelationRecordColumn {
  name: string;
  type: string;
  comment: string;
  relation_key: boolean;
}

export interface RelationRecordPage {
  page: number;
  page_size: number;
  total_rows: number;
  total_pages: number;
}

export interface RelationRecordCard {
  kind: "source" | "related";
  edge_id: string;
  relation_id: string;
  cardinality: TableRelationCardinality;
  source_column: string;
  target: RelationRecordTable;
  target_column: string;
  matched_columns: string[];
  columns: RelationRecordColumn[];
  rows: unknown[][];
  page: RelationRecordPage;
  matched_key_count: number;
  matched_keys_truncated: boolean;
  warning?: string | null;
}

export interface RelationRecordSearchResult {
  workspace_id: string;
  environment: string;
  table: RelationRecordTable;
  keyword: string;
  scanned_columns: string[];
  source_keys: Record<string, string | number | boolean | null>;
  cards: RelationRecordCard[];
}

export interface AiDataQueryRecord {
  id: string;
  source: string;
  description: string;
  workspace_id: string;
  workspace_name: string;
  environment: string;
  database_key: string;
  schema_name: string;
  table_name: string;
  keyword: string;
  created_at: string;
  task_id?: number | null;
  execution_status: "pending" | "succeeded" | "failed";
  executed_at?: string | null;
  result_card_count?: number | null;
  result_row_count?: number | null;
  duration_ms?: number | null;
  error_summary?: string | null;
}

export interface AiDataQueryLatest {
  record: AiDataQueryRecord | null;
}

export interface AiDataQueryHistory {
  items: AiDataQueryRecord[];
}

export interface AiInterfaceRequestListItem {
  id: string;
  workspace_id: string;
  workspace_name: string;
  source: string;
  description: string;
  interface_id: string;
  interface_name: string;
  service_name: string;
  method: string;
  path: string;
  environment: string;
  address_name?: string | null;
  login_account?: string | null;
  role_name?: string | null;
  request_preview: string;
  status_code?: number | null;
  success: boolean;
  duration_ms: number;
  response_bytes: number;
  response_truncated: boolean;
  created_at: string;
}

export interface AiInterfaceRequestList {
  items: AiInterfaceRequestListItem[];
  limit: number;
  offset: number;
  has_more: boolean;
  next_cursor?: string | null;
}

export interface AiInterfaceRequestDetail extends AiInterfaceRequestListItem {
  task_id?: number | null;
  tool_call_id?: number | null;
  plan_id?: string | null;
  request_sha256?: string | null;
  request: unknown;
  response: unknown;
  parameter_evidence: Record<string, unknown>;
}

export interface AiLogInvestigationListItem {
  id: string;
  workspace_id: string;
  workspace_name: string;
  source: string;
  description: string;
  environment: string;
  container_id: string;
  container_name: string;
  image: string;
  project_id?: string | null;
  project_name?: string | null;
  project_kind?: string | null;
  severity: "error" | "critical" | string;
  error_title: string;
  occurred_at?: string | null;
  occurrence_count: number;
  truncated: boolean;
  created_at: string;
  updated_at: string;
}

export interface AiLogInvestigationList {
  items: AiLogInvestigationListItem[];
  limit: number;
  offset: number;
  has_more: boolean;
  next_cursor?: string | null;
}

export interface AiLogInvestigationDetail extends AiLogInvestigationListItem {
  task_id?: number | null;
  error_excerpt: string;
  log_line_count: number;
  fingerprint: string;
}

export type AiTaskVisualizationStatus =
  | "investigating"
  | "resolved"
  | "failed"
  | "unclosed";

export type AiTaskIntentType =
  | "interface_discovery"
  | "interface_execute"
  | "data_query"
  | "task_execute"
  | "bug_investigate"
  | "bug_fix"
  | "code_change";

export type AiTaskIntentSource =
  | "agent_declared"
  | "compatibility_default"
  | "system_default";

export interface AiTaskVisualizationListItem {
  task_id: number;
  description: string;
  workspace_id: string;
  workspace_name: string;
  environment: string;
  agent_name: string;
  intent_type: AiTaskIntentType;
  intent_error_signal: boolean;
  intent_summary?: string | null;
  intent_source: AiTaskIntentSource;
  status: AiTaskVisualizationStatus;
  created_at: string;
  last_activity_at: string;
  tool_call_count: number;
  tool_error_count: number;
  running_call_count: number;
  data_query_count: number;
  interface_success_count: number;
  interface_failed_count: number;
  error_event_count: number;
}

export interface AiTaskVisualizationList {
  items: AiTaskVisualizationListItem[];
  limit: number;
  has_more: boolean;
  next_cursor?: string | null;
}

export interface AiTaskCodeLocation {
  path: string;
  line?: number | null;
  description: string;
}

export interface AiTaskVerificationItem {
  type: string;
  description: string;
  result: string;
  tool_call_id?: number | null;
}

export interface AiTaskVisualizationResult {
  task_id: number;
  status: "investigating" | "resolved" | "failed";
  summary: string;
  root_cause?: string | null;
  code_locations: AiTaskCodeLocation[];
  suggested_actions: string[];
  verification: AiTaskVerificationItem[];
  source: string;
  revision: number;
  created_at: string;
  updated_at: string;
  finalized_at?: string | null;
}

export type AiTaskChainHealthStatus =
  | "healthy"
  | "running"
  | "attention"
  | "failed"
  | "unused";

export interface AiTaskVisualizationDetail extends AiTaskVisualizationListItem {
  cwd: string;
  active_project_name?: string | null;
  result?: AiTaskVisualizationResult | null;
  related: {
    mcp_trace: boolean;
    data_visualization: boolean;
    interface_visualization: boolean;
    log_visualization: boolean;
  };
  chain_health: Array<{
    key: "mcp" | "data" | "interface" | "log" | "conclusion";
    label: string;
    status: AiTaskChainHealthStatus;
    summary: string;
  }>;
}

export interface AiTaskTimelineEvent {
  event_id: string;
  event_type:
    | "mcp_call"
    | "data_query"
    | "interface_request"
    | "log_investigation"
    | "task_result";
  title: string;
  status: string;
  occurred_at: string;
  summary: string;
  artifact_type: "mcp" | "data" | "interface" | "log" | "result";
  artifact_id: string;
}

export interface AiTaskTimeline {
  task_id: number;
  items: AiTaskTimelineEvent[];
  limit: number;
  has_more: boolean;
  next_cursor?: string | null;
}

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

export interface InterfaceForwardingInterface {
  id: string;
  service_id: string;
  name: string;
  path: string;
  method: string;
  description: string;
  controller_name: string;
  controller_description: string;
  operation_id: string;
  operation_kind: "read" | "write" | "destructive" | "unknown";
  crud_type: "create" | "read" | "update" | "delete" | "unknown";
  business_entity: string | null;
  business_action: string | null;
  business_scenario: string | null;
  aliases: string[] | null;
  positive_examples: string[] | null;
  negative_examples: string[] | null;
  intent_source: "generated" | "manual" | null;
  intent_confidence: number | null;
  table_effects: InterfaceForwardingTableEffect[];
  request_schema: Record<string, unknown>;
  response_schema: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  last_requested_at: string | null;
}

export interface InterfaceSemanticsWrite {
  business_entity: string;
  business_action: string;
  business_scenario: string;
  crud_type: InterfaceForwardingInterface["crud_type"];
  aliases: string[];
  positive_examples: string[];
  negative_examples: string[];
}

export interface InterfaceForwardingTableEffect {
  database_key: string;
  schema_name: string;
  table_name: string;
  effect_type: "select" | "insert" | "update" | "delete" | "soft_delete" | "upsert";
  response_contribution: "returned" | "filter_only" | "internal_only" | "unknown" | "none";
  source_file: string;
  source_class: string;
  source_method: string;
  call_path: string[];
  evidence_type: string;
  confidence: number;
}

export interface InterfaceForwardingService {
  id: string;
  name: string;
  interface_count: number;
  interfaces: InterfaceForwardingInterface[];
}

export interface InterfaceForwardingEnvironment {
  workspace_id: string;
  environment_key: string;
  display_name: string;
  sort_order: number;
  is_default: boolean;
  addresses: InterfaceForwardingAddress[];
}

export interface InterfaceForwardingAddress {
  id: string;
  workspace_id: string;
  environment_key: string;
  service_id: string | null;
  service_name: string | null;
  name: string;
  base_url: string;
  created_at: string;
  updated_at: string;
}

export interface InterfaceForwardingIdentity {
  id: string;
  workspace_id: string;
  environment_id: string;
  environment_key: string;
  environment_name?: string;
  login_account: string;
  role_name: string;
  request_header: string;
}

export interface InterfaceForwardingOverview {
  workspace_id: string;
  services: InterfaceForwardingService[];
  environments: InterfaceForwardingEnvironment[];
}

export interface InterfaceForwardingState {
  interface: InterfaceForwardingInterface & { workspace_id: string };
  last_params: {
    environment_id: string | null;
    environment_key: string | null;
    identity_id: string | null;
    request_body: string;
    response_body: string;
    updated_at: string;
  } | null;
}

export interface InterfaceForwardingLog {
  id: string;
  environment_name: string;
  identity_name: string | null;
  identity_role: string;
  request_url: string;
  request_body: string;
  response_body: string;
  status_code: number | null;
  success: boolean;
  duration_ms: number;
  intent_match_score: number;
  intent_match_evidence: {
    match_reasons?: string[];
    mismatches?: string[];
  };
  validation_status: "passed" | "warning" | "failed" | "not_configured";
  validation_result: {
    checks?: Record<string, { status?: string; message?: string }>;
    warnings?: string[];
  };
  created_at: string;
}

export interface InterfaceForwardingExecuteResult {
  success: boolean;
  status_code: number | null;
  duration_ms: number;
  response_body: string;
  response_headers: Record<string, string>;
}

export type ValueMappingStatus = "draft" | "published";
export type ValueMappingParameterLocation = "path" | "query" | "body";

export interface ValueMappingBinding {
  id?: string;
  interface_id: string;
  location: ValueMappingParameterLocation;
  parameter_path: string;
  required: boolean;
  interface_name?: string;
  interface_path?: string;
  method?: string;
  controller_name?: string;
  service_name?: string;
}

export interface ValueMapping {
  id: string;
  workspace_id: string;
  value_key: string;
  name: string;
  description: string;
  status: ValueMappingStatus;
  resolver_type: "database_column";
  database_alias: string;
  schema_name: string | null;
  table_name: string;
  value_column: string;
  search_columns: string[];
  display_columns: string[];
  filters: Record<string, JsonValue>;
  aliases: string[];
  bindings: ValueMappingBinding[];
  binding_count: number;
  version: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface ValueMappingDatabaseAlias {
  value: string;
  label: string;
}

export interface ValueMappingOverview {
  workspace_id: string;
  mappings: ValueMapping[];
  database_aliases: ValueMappingDatabaseAlias[];
}

export interface ValueMappingParameter {
  location: ValueMappingParameterLocation;
  parameter_path: string;
  required: boolean;
  type: string;
  description: string;
}

export interface ValueMappingInterfaceCandidate {
  id: string;
  name: string;
  controller_name: string;
  path: string;
  method: string;
  service_name: string;
  parameters: ValueMappingParameter[];
}

export interface ValueMappingInterfaceSearchResult {
  workspace_id: string;
  keyword: string;
  returned_count: number;
  interfaces: ValueMappingInterfaceCandidate[];
}

export interface ValueMappingWrite {
  workspace_id: string;
  value_key: string;
  name: string;
  description: string;
  status: ValueMappingStatus;
  database_alias: string;
  schema_name: string | null;
  table_name: string;
  value_column: string;
  search_columns: string[];
  display_columns: string[];
  filters: Record<string, JsonValue>;
  aliases: string[];
  bindings: Array<Omit<ValueMappingBinding, "id" | "interface_name" | "interface_path" | "method" | "controller_name" | "service_name">>;
}

export interface ValueMappingPreviewCandidate {
  value: JsonValue;
  label: string;
  labels: Record<string, JsonValue>;
}

export interface ValueMappingPreviewResult {
  mapping_id: string;
  value_key: string;
  environment: string;
  database_alias: string;
  keyword: string;
  candidates: ValueMappingPreviewCandidate[];
  returned_count: number;
  elapsed_ms: number;
  truncated: boolean;
}
