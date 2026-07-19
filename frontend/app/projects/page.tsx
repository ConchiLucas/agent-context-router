import type { ReactNode } from "react";
import Link from "next/link";

import { DocumentsView } from "@/components/documents-view";
import { ModalCloseButton } from "@/components/modal-close-button";
import { ProjectDocumentControls } from "@/components/project-document-controls";
import { ProjectDocumentPreviewShell } from "@/components/project-document-preview-shell";
import { ProjectCreateForm } from "@/components/project-create-form";
import { getProjects } from "@/lib/api";
import { mappingStatusLabel } from "@/lib/document-health";

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
      <section className="section">
        <ProjectCreateForm />
      </section>
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
                  <span className={`badge mapping-${project.mapping_status}`}>
                    {mappingStatusLabel(project.mapping_status)}
                  </span>
                </div>

                <div className="project-card-content">
                  <div className="project-health-grid">
                    <ProjectFact label="Code root" value={project.root_path ?? "Not configured"} />
                    <ProjectFact
                      label="Document mapping"
                      value={project.docs_path ?? "Not mapped"}
                    />
                    <ProjectFact label="Status" value={mappingStatusLabel(project.mapping_status)} />
                    <ProjectFact
                      label="Documents"
                      value={`${project.sync_summary.indexed} indexed / ${project.sync_summary.reachable} reachable / ${project.sync_summary.orphan} orphan`}
                    />
                    <ProjectFact
                      label="Broken links"
                      value={String(project.sync_summary.broken_links)}
                    />
                    <ProjectFact
                      label="Last synced"
                      value={formatLastSynced(project.last_synced_at)}
                    />
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
                  <ProjectDocumentControls project={project} />
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
