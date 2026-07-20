export interface ProjectSummary {
  id: string;
  name: string;
  agents_path: string;
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
