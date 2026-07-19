export type ProjectSummary = {
  id: string;
  slug: string;
  name: string;
  root_path: string | null;
  description: string;
  parent_slug: string | null;
  document_count: number;
  active_document_count: number;
  trace_count: number;
  child_project_count: number;
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
  links: DocumentLinkSummary[];
};

export type DocumentListResponse = {
  documents: DocumentSummary[];
};

export type DocumentSyncResponse = {
  project_slug: string;
  docs_dir: string;
  indexed_count: number;
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
  content_markdown: string;
  links: DocumentLinkSummary[];
};

export type DocumentLinkSummary = {
  target_document_id: string | null;
  target_path: string;
  label: string;
  relation_type: string;
  sort_order: number;
};

export type RetrievalHit = {
  id: string;
  document_id: string;
  document_title: string;
  rank: number;
  reason: string;
  score: number;
  was_returned: boolean;
  feedback: TraceFeedback | null;
};

export type TraceSummary = {
  id: string;
  project_slug: string;
  project_name: string;
  task: string;
  cwd: string | null;
  area: string | null;
  source: string | null;
  created_at: string;
  returned_document_count: number;
  read_event_count: number;
  feedback_count: number;
};

export type TraceListResponse = {
  traces: TraceSummary[];
};

export type TraceEvent = {
  id: string;
  event_type: "prepare" | "read" | "feedback" | "error" | string;
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

export type TraceFeedback = "useful" | "unnecessary" | "missing" | "stale";

export type UsageCard = {
  id: string;
  slug: string;
  title: string;
  description: string;
  content_markdown: string;
  sort_order: number;
  is_builtin: boolean;
  created_at: string;
  updated_at: string;
};

export type UsageCardListResponse = {
  cards: UsageCard[];
};
