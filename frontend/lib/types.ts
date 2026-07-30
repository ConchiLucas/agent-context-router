export type ProjectKind = "frontend" | "backend";
export type DatabaseEnvironment = "test" | "uat";
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

export interface ProjectSummary {
  id: string;
  name: string;
  project_kind: ProjectKind;
  project_type?: string;
  agents_path: string;
  document_relative_path: string;
  workspace_id?: string | null;
  workspace_name?: string | null;
  workspace_enabled?: boolean | null;
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
  enabled: boolean;
  project_count: number;
  error_project_count: number;
  data_source_count: number;
  database_count: number;
  database_authorization_count: number;
  created_at?: string;
  updated_at: string;
}

export interface WorkspaceCreate {
  name: string;
  workspace_type: string;
  root_path: string;
  enabled?: boolean;
}

export interface WorkspaceUpdate {
  name: string;
  workspace_type: string;
  root_path: string;
}

export interface WorkspaceProjectCreate {
  name: string;
  relative_path: string;
  document_relative_path: string;
  project_kind: ProjectKind;
}

export interface WorkspaceProjectUpdate {
  name: string;
  relative_path: string;
  document_relative_path: string;
  project_kind: ProjectKind;
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
  workspace_enabled: boolean;
  link_enabled: boolean;
  readonly: boolean;
  database_available: boolean;
  database_system: boolean;
  source_enabled: boolean;
  status: string;
}

export interface WorkspaceDataSourceUsage {
  id: string;
  name: string;
  category: string;
  engine: DatabaseEngine;
  enabled: boolean;
  database_count: number;
  assignment_count: number;
  project_count: number;
  assignments: WorkspaceDataSourceAssignment[];
}

export interface WorkspaceDataSourceSummary {
  workspace_id: string;
  workspace_enabled: boolean;
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
  source_enabled: boolean;
  readonly: boolean;
  link_enabled: boolean;
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
  candidates: Record<DatabaseEnvironment, DatabaseEnvironmentTarget[]>;
}

export interface WorkspaceDatabaseEnvironmentSummary {
  mapping_count: number;
  complete_count: number;
  issue_count: number;
}

export interface WorkspaceDatabaseEnvironmentMappings {
  workspace_id: string;
  configured: boolean;
  enabled: boolean;
  active_environment: DatabaseEnvironment | null;
  revision: number;
  summary: WorkspaceDatabaseEnvironmentSummary;
  projects: WorkspaceDatabaseEnvironmentProject[];
}

export interface WorkspaceDatabaseEnvironmentMappingUpdate {
  id?: string;
  project_id: string;
  logical_name: string;
  mcp_alias: string;
  targets: Record<DatabaseEnvironment, string | null>;
}

export interface WorkspaceDatabaseEnvironmentMappingsUpdate {
  expected_revision: number;
  mappings: WorkspaceDatabaseEnvironmentMappingUpdate[];
}

export interface WorkspaceDatabaseEnvironmentSwitch {
  environment: DatabaseEnvironment;
  expected_revision: number;
}

export interface WorkspaceEnvironmentConfig {
  workspace_id: string;
  configured: boolean;
  active_environment: DatabaseEnvironment | null;
  revision: number;
  environments: Record<DatabaseEnvironment, EnvironmentJsonObject>;
  active_config: EnvironmentJsonObject | null;
}

export interface WorkspaceEnvironmentConfigUpdate {
  expected_revision: number;
  environments: Record<DatabaseEnvironment, EnvironmentJsonObject>;
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
  | "postgresql"
  | "sqlserver"
  | "sqlite"
  | "oracle"
  | "clickhouse";

export interface DataSourcePayload {
  name: string;
  category: string;
  engine: DatabaseEngine;
  description: string;
  connection_config: Record<string, string | number | boolean>;
  enabled: boolean;
}

export interface DataSourceSummary extends DataSourcePayload {
  id: string;
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

export interface DataSourceDatabasePayload {
  remote_name: string;
  display_name: string;
  namespace_type: "database" | "schema" | "file";
  available: boolean;
  system_database: boolean;
  metadata: Record<string, string | number | boolean>;
}

export interface DataSourceDatabaseSummary
  extends DataSourceDatabasePayload {
  id: string;
  data_source_id: string;
  project_count: number;
  created_at: string;
  updated_at: string;
}

export interface DataSourceDatabaseSyncResult {
  discovered_count: number;
  created_count: number;
  unavailable_count: number;
  databases: DataSourceDatabaseSummary[];
}

export interface ProjectDatabaseLinkPayload {
  project_id: string;
  alias: string;
  mcp_alias?: string | null;
  purpose: string;
  enabled: boolean;
  readonly: boolean;
  allowed_schemas: string[];
  max_rows: number;
  max_result_bytes: number;
  query_timeout_ms: number;
}

export interface ProjectDatabaseLinkSummary
  extends ProjectDatabaseLinkPayload {
  id: string;
  project_name: string;
  database_id: string;
  database_name: string;
  data_source_id: string;
  data_source_name: string;
  engine: DatabaseEngine;
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
  enabled: boolean;
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
  path: string;
  title?: string;
  summary?: string;
  error?: string;
  children: ContextDocumentNode[];
}

export interface PreparedProject {
  project_id: string;
  name: string;
  node_count: number;
  relative_path: string;
  document_relative_path: string;
  project_kind: ProjectKind;
}

export interface PreparedWorkspace {
  workspace_id: string;
  name: string;
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
  workspace: PreparedWorkspace;
  projects: PreparedProject[];
  active_project?: PreparedProject | null;
  project?: PreparedProject | null;
  documents: ContextDocumentNode;
  databases: PreparedDatabase[];
  database_environment?: PreparedDatabaseEnvironment | null;
  environment_config?: EnvironmentJsonObject | null;
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
  | "search_context_documents"
  | "read_context_document"
  | "search_database_objects"
  | "execute_database_query";

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
