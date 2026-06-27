import Link from "next/link";

import { getDocuments, getProjects, getTraces } from "@/lib/api";

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
    { label: "Projects", value: String(projects.length) },
    { label: "Active Docs", value: String(documents.filter((doc) => doc.status === "active").length) },
    { label: "Prepare Calls", value: String(traces.length) },
    { label: "Feedback", value: String(feedbackCount) },
  ];

  return (
    <>
      <header>
        <h1 className="page-title">Context Routing Dashboard</h1>
        <p className="page-subtitle">Projects, context documents, and recent trace activity.</p>
      </header>

      <section className="section grid grid-4">
        {metrics.map((metric) => (
          <div className="panel metric" key={metric.label}>
            <span className="metric-label">{metric.label}</span>
            <strong className="metric-value">{metric.value}</strong>
          </div>
        ))}
      </section>

      <section className="section grid two-column">
        <div className="panel">
          <h2 className="section-title">Recent Traces</h2>
          {traces.length === 0 ? (
            <p className="page-subtitle">No trace records yet.</p>
          ) : (
            <div className="stack">
              {traces.slice(0, 5).map((trace) => (
                <Link className="row-link" href={`/traces/${trace.id}`} key={trace.id}>
                  <strong>{trace.task}</strong>
                  <span>{trace.project_slug}</span>
                </Link>
              ))}
            </div>
          )}
        </div>
        <div className="panel">
          <h2 className="section-title">CLI Entry</h2>
          <pre className="code-block">{`ctx prepare --project <project> --task "<task>"`}</pre>
        </div>
      </section>
    </>
  );
}
