export type ProjectSummary = {
  id: string;
  slug: string;
  name: string;
  root_path: string | null;
  description: string;
  document_count: number;
  active_document_count: number;
};

export type ProjectDetail = ProjectSummary & {
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
};

export type DocumentListResponse = {
  documents: DocumentSummary[];
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
  payload: Record<string, string | number | boolean | null>;
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
  agent_name: string | null;
  created_at: string;
  retrieval_hits: RetrievalHit[];
  events: TraceEvent[];
};

export type TraceFeedback = "useful" | "unnecessary" | "missing" | "stale";
