import type { ReactNode } from "react";
import Link from "next/link";

import { DocumentsView } from "@/components/documents-view";
import { ModalCloseButton } from "@/components/modal-close-button";
import { ProjectDocumentPreviewShell } from "@/components/project-document-preview-shell";
import { ProjectLinkReloadButton } from "@/components/project-link-reload-button";
import { getProjects } from "@/lib/api";

type ProjectsPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function ProjectsPage({ searchParams }: ProjectsPageProps) {
  const params = await searchParams;
  const activePanel = singleValue(params.panel);
  const activeProject = singleValue(params.project) || undefined;
  const activeDocument = singleValue(params.document);
  const area = singleValue(params.area);
  const docType = singleValue(params.doc_type);
  const tag = singleValue(params.tag);
  const status = singleValue(params.status);
  const documentView = singleValue(params.view);
  const result = await Promise.allSettled([getProjects()]);
  const projects = result[0].status === "fulfilled" ? result[0].value.projects : [];
  const documentsPanelHref = projectPanelHref({
    panel: "documents",
    project: activeProject,
    area,
    doc_type: docType,
    tag,
    status,
    view: documentView,
  });
  return (
    <>
      <header>
        <h1 className="page-title">Projects</h1>
        <p className="page-subtitle">Top-level workspaces and their subprojects.</p>
      </header>
      <section className="section grid project-grid">
        {projects.length === 0 ? (
          <div className="panel">
            <p className="page-subtitle">No projects indexed yet.</p>
          </div>
        ) : (
          projects.map((project) => {
            const encodedSlug = encodeURIComponent(project.slug);

            return (
              <article className="panel project-card" key={project.slug}>
                <div className="project-card-header">
                  <div>
                    <Link className="project-card-title" href={`/projects/${project.slug}`}>
                      {project.name}
                    </Link>
                    <p className="page-subtitle">{project.slug}</p>
                  </div>
                  <span className="badge">{project.child_project_count} subprojects</span>
                </div>

                <div className="project-card-content">
                  <div className="project-card-meta">
                    <span>Root</span>
                    <strong>{project.root_path ?? "no root path"}</strong>
                  </div>

                  <div className="project-card-stats">
                    <div>
                      <span>Documents</span>
                      <strong>{project.document_count}</strong>
                      <small>{project.active_document_count} active</small>
                    </div>
                    <div>
                      <span>MCP Tasks</span>
                      <strong>{project.trace_count}</strong>
                      <small>recorded calls</small>
                    </div>
                  </div>
                </div>

                <div className="project-card-actions">
                  <Link
                    className="button active"
                    href={`/projects?panel=documents&project=${encodedSlug}`}
                  >
                    Documents
                  </Link>
                  <Link
                    className="button"
                    href={`/tasks?project=${encodedSlug}`}
                  >
                    Tasks
                  </Link>
                  <ProjectLinkReloadButton
                    disabled={!project.root_path}
                    projectSlug={project.slug}
                  />
                </div>
              </article>
            );
          })
        )}
      </section>
      {activePanel === "documents" ? (
        <ProjectPanel backHref="/projects">
          <ProjectDocumentPreviewShell
            closeHref={documentsPanelHref}
            initialDocumentId={activeDocument}
          >
            <DocumentsView
              baseHref="/projects"
              detailHref={(document) =>
                projectPanelHref({
                  panel: "documents",
                  project: activeProject,
                  area,
                  doc_type: docType,
                  tag,
                  status,
                  view: documentView,
                  document: document.id,
                })
              }
              filters={{
                project: activeProject,
                area,
                doc_type: docType,
                tag,
                status,
              }}
              hiddenFields={{ panel: "documents" }}
              subtitle={
                activeProject
                  ? `Context documents for ${activeProject}.`
                  : "Context documents and routing metadata."
              }
              view={documentView}
            />
          </ProjectDocumentPreviewShell>
        </ProjectPanel>
      ) : null}
    </>
  );
}

function ProjectPanel({
  backHref,
  children,
}: Readonly<{
  backHref: string;
  children: ReactNode;
}>) {
  return (
    <aside className="project-modal" aria-modal="true" role="dialog">
      <ModalCloseButton className="icon-close-button project-modal-close" href={backHref} />
      <div className="project-modal-content">{children}</div>
    </aside>
  );
}

function singleValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function projectPanelHref(params: {
  panel: "documents";
  project?: string;
  area?: string;
  doc_type?: string;
  tag?: string;
  status?: string;
  view?: string;
  document?: string;
}) {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) {
      searchParams.set(key, value);
    }
  }
  return `/projects?${searchParams.toString()}`;
}
