import Link from "next/link";

import { getProject } from "@/lib/api";

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
        <p className="page-subtitle">{project.root_path ?? project.slug}</p>
      </header>

      <section className="section grid grid-4">
        <div className="panel metric">
          <span className="metric-label">Documents</span>
          <strong className="metric-value">{project.document_count}</strong>
        </div>
        <div className="panel metric">
          <span className="metric-label">Active</span>
          <strong className="metric-value">{project.active_document_count}</strong>
        </div>
        <div className="panel metric">
          <span className="metric-label">Subprojects</span>
          <strong className="metric-value">{project.child_project_count}</strong>
        </div>
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

      <section className="section panel">
        <h2 className="section-title">AI_CONTEXT_INDEX.md</h2>
        <pre className="code-block">{project.routing_template}</pre>
      </section>
    </>
  );
}
