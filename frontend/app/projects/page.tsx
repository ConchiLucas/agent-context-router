import Link from "next/link";

import { getProjects } from "@/lib/api";

export default async function ProjectsPage() {
  const result = await Promise.allSettled([getProjects()]);
  const projects = result[0].status === "fulfilled" ? result[0].value.projects : [];
  return (
    <>
      <header>
        <h1 className="page-title">Projects</h1>
        <p className="page-subtitle">Routing roots and generated index files.</p>
      </header>
      <section className="section grid">
        {projects.length === 0 ? (
          <div className="panel">
            <p className="page-subtitle">No projects indexed yet.</p>
          </div>
        ) : (
          projects.map((project) => (
            <Link className="panel row-card" href={`/projects/${project.slug}`} key={project.slug}>
              <div>
                <h2 className="section-title">{project.name}</h2>
                <p className="page-subtitle">{project.slug}</p>
              </div>
              <div className="row-meta">
                <span className="badge">{project.active_document_count} active docs</span>
                <span>{project.root_path ?? "no root path"}</span>
              </div>
            </Link>
          ))
        )}
      </section>
    </>
  );
}
