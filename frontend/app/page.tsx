import Link from "next/link";

import { getDocuments, getProjects, getTraces } from "@/lib/api";
import { CliTerminal } from "@/components/cli-terminal";

export default async function DashboardPage() {
  const [projectsResult, documentsResult, tracesResult] = await Promise.allSettled([
    getProjects(),
    getDocuments(),
    getTraces(),
  ]);
  const projects = projectsResult.status === "fulfilled" ? projectsResult.value.projects : [];
  const documents = documentsResult.status === "fulfilled" ? documentsResult.value.documents : [];
  const traces = tracesResult.status === "fulfilled" ? tracesResult.value.traces : [];
  const feedbackCount = traces.reduce((total, trace) => total + trace.feedback_count, 0);

  const metrics = [
    { 
      label: "Projects", 
      value: String(projects.length),
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
        </svg>
      )
    },
    { 
      label: "Active Docs", 
      value: String(documents.filter((doc) => doc.status === "active").length),
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent-secondary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
          <path d="M14 2v4a2 2 0 0 0 2 2h4" />
        </svg>
      )
    },
    { 
      label: "Prepare Calls", 
      value: String(traces.length),
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
        </svg>
      )
    },
    { 
      label: "Feedback", 
      value: String(feedbackCount),
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#e11d48" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      )
    },
  ];

  return (
    <>
      <header style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
        <h1 className="page-title">Context Routing Dashboard</h1>
        <p className="page-subtitle">Monitor projects, context documents, and recent trace activity.</p>
      </header>

      <section className="section grid grid-4">
        {metrics.map((metric) => (
          <div className="panel metric" key={metric.label}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span className="metric-label">{metric.label}</span>
              {metric.icon}
            </div>
            <strong className="metric-value" style={{ marginTop: "0.25rem" }}>{metric.value}</strong>
          </div>
        ))}
      </section>

      <section className="section grid two-column">
        <div className="panel" style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 className="section-title" style={{ margin: 0 }}>Recent Traces</h2>
            <Link href="/traces" style={{ fontSize: "0.85rem", color: "var(--accent)", fontWeight: 600 }}>
              View all &rarr;
            </Link>
          </div>
          {traces.length === 0 ? (
            <p className="page-subtitle">No trace records yet.</p>
          ) : (
            <div className="stack">
              {traces.slice(0, 5).map((trace) => (
                <Link className="row-link" href={`/traces/${trace.id}`} key={trace.id}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}>
                    <strong style={{ fontSize: "0.95rem", color: "#f1f5f9", fontWeight: 600 }}>{trace.task}</strong>
                    <span className="badge" style={{ fontSize: "0.7rem", padding: "0.15rem 0.45rem", whiteSpace: "nowrap" }}>
                      {trace.project_slug}
                    </span>
                  </div>
                  <div className="row-meta" style={{ marginTop: "0.25rem", display: "flex", gap: "1rem" }}>
                    <span style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
                        <path d="M14 2v4a2 2 0 0 0 2 2h4" />
                      </svg>
                      {trace.returned_document_count} returned
                    </span>
                    <span style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10" />
                        <polyline points="12 6 12 12 16 14" />
                      </svg>
                      {trace.read_event_count} reads
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
        
        <div className="panel" style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
          <h2 className="section-title" style={{ margin: 0 }}>CLI Entry</h2>
          <p className="page-subtitle" style={{ margin: 0 }}>
            Run this command from your terminal to trigger context retrieval and generate a new routing trace:
          </p>
          <CliTerminal command='ctx prepare --project <project> --task "<task>"' />
        </div>
      </section>
    </>
  );
}
