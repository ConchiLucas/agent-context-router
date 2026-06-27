import type { ReactNode } from "react";
import Link from "next/link";

import { DocumentDetailView } from "@/components/document-detail-view";
import { DocumentsView } from "@/components/documents-view";
import { TracesView } from "@/components/traces-view";
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
  const source = singleValue(params.source);
  const result = await Promise.allSettled([getProjects()]);
  const projects = result[0].status === "fulfilled" ? result[0].value.projects : [];
  const documentsPanelHref = projectPanelHref({
    panel: "documents",
    project: activeProject,
    area,
    doc_type: docType,
    tag,
    status,
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
                      <span>Traces</span>
                      <strong>{project.trace_count}</strong>
                      <small>prepare calls</small>
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
                    href={`/projects?panel=traces&project=${encodedSlug}`}
                  >
                    Traces
                  </Link>
                </div>
              </article>
            );
          })
        )}
      </section>
      {activePanel === "documents" ? (
        <ProjectPanel backHref="/projects">
          <DocumentsView
            detailHref={(document) =>
              projectPanelHref({
                panel: "documents",
                project: activeProject,
                area,
                doc_type: docType,
                tag,
                status,
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
          />
          {activeDocument ? (
            <NestedProjectPanel backHref={documentsPanelHref}>
              <DocumentDetailView
                backHref={documentsPanelHref}
                backLabel="Documents"
                documentId={activeDocument}
                showInlineBack={false}
              />
            </NestedProjectPanel>
          ) : null}
        </ProjectPanel>
      ) : null}
      {activePanel === "traces" ? (
        <ProjectPanel backHref="/projects">
          <TracesView
            filters={{
              project: activeProject,
              area,
              source,
            }}
            subtitle={
              activeProject
                ? `Prepare calls, read history, and feedback for ${activeProject}.`
                : "Prepare calls, read history, and feedback."
            }
          />
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
      <div className="project-modal-toolbar">
        <Link className="button" href={backHref}>
          Back
        </Link>
      </div>
      <div className="project-modal-content">{children}</div>
    </aside>
  );
}

function singleValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function NestedProjectPanel({
  backHref,
  children,
}: Readonly<{
  backHref: string;
  children: ReactNode;
}>) {
  return (
    <aside className="project-modal nested-project-modal" aria-modal="true" role="dialog">
      <div className="project-modal-toolbar">
        <Link className="button" href={backHref}>
          Back
        </Link>
      </div>
      <div className="project-modal-content">{children}</div>
    </aside>
  );
}

function projectPanelHref(params: {
  panel: "documents" | "traces";
  project?: string;
  area?: string;
  doc_type?: string;
  tag?: string;
  status?: string;
  source?: string;
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
