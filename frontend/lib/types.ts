export interface ProjectSummary {
  id: string;
  name: string;
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
  agents_path: string;
}

export interface ProjectUpdate {
  name: string;
  agents_path: string;
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

export interface PrepareTaskContextResult {
  task_id: number;
  project: PreparedProject;
  documents: ContextDocumentNode;
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

export interface ContextTaskReadHistory {
  task_id: number;
  task: string;
  project_name: string;
  agent_name?: string;
  created_at: string;
  calls: ContextReadHistoryCall[];
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
