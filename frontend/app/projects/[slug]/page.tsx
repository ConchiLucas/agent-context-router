import Link from "next/link";

import { ProjectDocumentControls } from "@/components/project-document-controls";
import { getProject } from "@/lib/api";
import { mappingStatusLabel, syncSummaryText } from "@/lib/document-health";

type ProjectPageProps = {
  params: Promise<{
    slug: string;
  }>;
};

export default async function ProjectDetailPage({ params }: ProjectPageProps) {
  const { slug } = await params;
  const result = await Promise.allSettled([getProject(slug)]);
  const project = result[0].status === "fulfilled" ? result[0].value : null;

  if (project === null) {
    return (
      <section className="panel">
        <h1 className="page-title">Project unavailable</h1>
        <p className="page-subtitle">{slug}</p>
      </section>
    );
  }

  return (
    <>
      <header>
        <h1 className="page-title">{project.name}</h1>
        <p className="page-subtitle">{project.slug}</p>
      </header>

      <section className="section grid grid-4">
        <div className="panel metric">
          <span className="metric-label">Indexed</span>
          <strong className="metric-value">{project.sync_summary.indexed}</strong>
        </div>
        <div className="panel metric">
          <span className="metric-label">Reachable</span>
          <strong className="metric-value">{project.sync_summary.reachable}</strong>
        </div>
        <div className="panel metric">
          <span className="metric-label">Orphan</span>
          <strong className="metric-value">{project.sync_summary.orphan}</strong>
        </div>
        <Link className="panel metric" href={`/tasks?project=${encodeURIComponent(project.slug)}`}>
          <span className="metric-label">MCP Tasks</span>
          <strong className="metric-value">{project.trace_count}</strong>
        </Link>
      </section>

      <section className="section panel project-detail-mapping">
        <div className="project-detail-heading">
          <div>
            <h2 className="section-title">Document mapping</h2>
            <p className="page-subtitle">
              Choose a mounted document directory, then sync AGENTS.md and docs/**/*.md.
            </p>
          </div>
          <span className={`badge mapping-${project.mapping_status}`}>
            {mappingStatusLabel(project.mapping_status)}
          </span>
        </div>
        <div className="project-health-grid">
          <ProjectFact label="Code root" value={project.root_path ?? "Not configured"} />
          <ProjectFact label="Document mapping" value={project.docs_path ?? "Not mapped"} />
          <ProjectFact label="Status" value={mappingStatusLabel(project.mapping_status)} />
          <ProjectFact label="Documents" value={syncSummaryText(project.sync_summary)} />
          <ProjectFact label="Broken links" value={String(project.sync_summary.broken_links)} />
          <ProjectFact label="Last synced" value={formatLastSynced(project.last_synced_at)} />
        </div>
        <ProjectDocumentControls project={project} />
      </section>

      {project.children.length > 0 ? (
        <section className="section">
          <h2 className="section-title">Subprojects</h2>
          <div className="grid">
            {project.children.map((child) => (
              <Link className="row-card" href={`/projects/${child.slug}`} key={child.slug}>
                <div>
                  <h3 className="section-title">{child.name}</h3>
                  <p className="page-subtitle">{child.slug}</p>
                </div>
                <div className="row-meta">
                  <span className="badge">{child.active_document_count} active docs</span>
                  <span>{child.root_path ?? "no root path"}</span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

    </>
  );
}

function ProjectFact({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="project-fact">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatLastSynced(value: string | null) {
  return value ? new Date(value).toLocaleString("en-GB") : "Never";
}
