export interface ProjectSummary {
  id: string;
  name: string;
  project_type: string;
  agents_path: string;
  enabled: boolean;
  node_count: number;
  refreshed_at: string | null;
  error: string | null;
}

export interface DocumentTreeNode {
  id: string;
  description: string;
  path: string;
  relative_path: string | null;
  error: string | null;
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

export interface ProjectCreate {
  name: string;
  project_type: string;
  agents_path: string;
}

export interface ProjectUpdate {
  name: string;
  project_type: string;
  agents_path: string;
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
}

export interface PreparedDatabase {
  database: string;
  engine: string;
  name: string;
  purpose: string;
  readonly: boolean;
  capabilities: string[];
}

export interface PrepareTaskContextResult {
  task_id: number;
  project: PreparedProject;
  documents: ContextDocumentNode;
  databases: PreparedDatabase[];
  warnings?: string[];
}

export interface ContextTaskSummary {
  task_id: number;
  task: string;
  cwd: string;
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
  project_name: string;
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

export type McpTraceCallSource =
  | "server"
  | "gateway"
  | "reported"
  | "legacy";

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
  error_code?: string | null;
  artifacts: McpTraceArtifact[];
}

export interface McpTraceDetail extends McpTraceSummary {
  calls: McpTraceToolCall[];
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
  project_count: number;
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
  project_id: string;
  project_name?: string;
  task_id?: number;
  read_call_id?: number;
  started_at: string;
  finished_at: string;
  stages: McpIntegrationTestStage[];
}
