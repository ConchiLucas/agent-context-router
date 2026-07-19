import type { TraceSummary } from "@/lib/types";
import Link from "next/link";

export function TraceTimeline({ trace }: Readonly<{ trace: TraceSummary }>) {
  return (
    <Link className="panel row-card" href={`/traces/${trace.id}`} style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.75rem" }}>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <span className="badge" style={{ fontSize: "0.75rem" }}>
            {trace.project_slug}
          </span>
          {trace.area ? (
            <span className="badge" style={{ fontSize: "0.75rem" }}>
              {trace.area}
            </span>
          ) : null}
          {trace.source ? (
            <span className="badge" style={{ fontSize: "0.75rem" }}>
              {trace.source}
            </span>
          ) : null}
        </div>
        <span className="page-subtitle" style={{ fontSize: "0.75rem", fontFamily: "ui-monospace, monospace" }}>
          {trace.id}
        </span>
      </div>
      <h3 style={{ margin: 0, color: "#f8fafc", fontSize: "1.05rem", fontWeight: 700 }}>
        {trace.task}
      </h3>
      <div className="split-row" style={{ display: "flex", gap: "1rem", marginTop: "0.25rem", borderTop: "1px dashed var(--line)", paddingTop: "0.75rem" }}>
        <span style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.82rem" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
            <path d="M14 2v4a2 2 0 0 0 2 2h4" />
          </svg>
          <strong>{trace.returned_document_count}</strong> fallback docs
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.82rem" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent-secondary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          <strong>{trace.read_event_count}</strong> read path
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.82rem" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#e11d48" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <strong>{trace.feedback_count}</strong> feedback
        </span>
      </div>
    </Link>
  );
}
