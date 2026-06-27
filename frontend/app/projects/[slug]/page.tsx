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
      </section>

      <section className="section panel">
        <h2 className="section-title">AI_CONTEXT_INDEX.md</h2>
        <pre className="code-block">{project.routing_template}</pre>
      </section>
    </>
  );
}
