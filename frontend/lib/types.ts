export type ProjectSummary = {
  id: string;
  slug: string;
  name: string;
  root_path: string | null;
  docs_path: string | null;
  description: string;
  parent_slug: string | null;
  mapping_status: string;
  last_synced_at: string | null;
  last_sync_status: string;
  sync_summary: SyncSummary;
  document_count: number;
  active_document_count: number;
  trace_count: number;
  child_project_count: number;
};

export type SyncSummary = {
  indexed: number;
  reachable: number;
  orphan: number;
  broken_links: number;
  pruned: number;
};

export type DocumentMappingCandidate = {
  docs_path: string;
  markdown_count: number;
  mapped_project_slug: string | null;
};

export type DocumentMappingCandidateListResponse = {
  candidates: DocumentMappingCandidate[];
};

export type DocumentMappingResponse = {
  project_slug: string;
  docs_path: string;
  last_synced_at: string | null;
  last_sync_status: string;
  last_sync_summary: Record<string, number>;
};

export type ProjectDetail = ProjectSummary & {
  children: ProjectSummary[];
  routing_template: string;
};

export type ProjectListResponse = {
  projects: ProjectSummary[];
};

export type DocumentSummary = {
  id: string;
  project_slug: string;
  title: string;
  source_path: string;
  area: string | null;
  doc_type: string;
  tags: string[];
  status: string;
  is_reachable: boolean;
  graph_depth: number | null;
  broken_link_count: number;
  links: DocumentLinkSummary[];
};

export type DocumentListResponse = {
  documents: DocumentSummary[];
};

export type DocumentSyncResponse = {
  project_slug: string;
  docs_path: string;
  indexed_count: number;
  reachable_count: number;
  orphan_count: number;
  broken_link_count: number;
  link_count: number;
  pruned_count: number;
  indexed_document_ids: string[];
  pruned_document_ids: string[];
};

export type DocumentDetail = {
  id: string;
  trace_id: string | null;
  title: string;
  source_path: string;
  area: string | null;
  doc_type: string;
  tags: string[];
  status: string;
  is_reachable: boolean;
  graph_depth: number | null;
  broken_link_count: number;
  content_markdown: string;
  links: DocumentLinkSummary[];
};

export type DocumentLinkSummary = {
  target_document_id: string | null;
  target_path: string;
  label: string;
  relation_type: string;
  sort_order: number;
  is_broken: boolean;
};

export type RetrievalHit = {
  id: string;
  document_id: string;
  document_title: string;
  rank: number;
  reason: string;
  score: number;
  was_returned: boolean;
};

export type TraceSummary = {
  id: string;
  project_slug: string;
  project_name: string;
  task: string;
  cwd: string | null;
  area: string | null;
  source: string | null;
  agent_name: string | null;
  created_at: string;
  returned_document_count: number;
  read_event_count: number;
  mcp_duration_ms: number;
};

export type TraceListResponse = {
  traces: TraceSummary[];
};

export type TraceEvent = {
  id: string;
  event_type: "prepare" | "read" | "error" | string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type TraceDetail = {
  id: string;
  project: {
    id: string;
    slug: string;
    name: string;
  };
  task: string;
  cwd: string | null;
  area: string | null;
  entrypoint_path: string | null;
  entrypoint_rule: string | null;
  route_hint: string | null;
  source: string | null;
  agent_name: string | null;
  created_at: string;
  retrieval_hits: RetrievalHit[];
  events: TraceEvent[];
};
