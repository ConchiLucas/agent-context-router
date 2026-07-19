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

