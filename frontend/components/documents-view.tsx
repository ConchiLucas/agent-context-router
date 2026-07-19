import { DocumentGraph } from "@/components/document-graph";
import { DocumentTable } from "@/components/document-table";
import { getDocuments, getProjects } from "@/lib/api";
import type { DocumentSummary } from "@/lib/types";
import Link from "next/link";

export type DocumentFilters = {
  project?: string;
  area?: string;
  doc_type?: string;
  tag?: string;
  status?: string;
};

export type DocumentViewMode = "graph" | "list";

type DocumentsViewProps = Readonly<{
  filters: DocumentFilters;
  baseHref?: string;
  detailHref?: (document: DocumentSummary) => string;
  hiddenFields?: Record<string, string>;
  subtitle?: string;
  view?: string;
}>;

export async function DocumentsView({
  filters,
  baseHref = "/documents",
  detailHref,
  hiddenFields = {},
  subtitle = "Context documents and routing metadata.",
  view = "graph",
}: DocumentsViewProps) {
  const [documentsResult, projectsResult] = await Promise.allSettled([
    getDocuments(filters),
    getProjects({ includeChildren: true }),
  ]);
  const documents =
    documentsResult.status === "fulfilled" ? documentsResult.value.documents : [];
  const projects = projectsResult.status === "fulfilled" ? projectsResult.value.projects : [];
  const areas = unique(documents.map((document) => document.area).filter(Boolean));
  const docTypes = unique(documents.map((document) => document.doc_type));
  const tags = unique(documents.flatMap((document) => document.tags));
  const activeView: DocumentViewMode = view === "list" ? "list" : "graph";

  return (
    <>
      <header>
        <h1 className="page-title">Documents</h1>
        <p className="page-subtitle">{subtitle}</p>
      </header>
      <section className="section panel">
        <div className="document-view-toolbar">
          <div>
            <h2 className="section-title">Context Map</h2>
            <p className="page-subtitle">
              从 AGENTS.md 查看可达层级、孤立文档和断链。
            </p>
          </div>
          <div className="segmented-control" aria-label="Document view mode">
            <Link
              className={activeView === "graph" ? "active" : ""}
              href={documentsViewHref({ baseHref, filters, hiddenFields, view: "graph" })}
            >
              Graph
            </Link>
            <Link
              className={activeView === "list" ? "active" : ""}
              href={documentsViewHref({ baseHref, filters, hiddenFields, view: "list" })}
            >
              List
            </Link>
          </div>
        </div>
        <form className="filter-grid">
          {Object.entries(hiddenFields).map(([name, value]) => (
            <input key={name} name={name} type="hidden" value={value} />
          ))}
          <input name="view" type="hidden" value={activeView} />
          <label>
            <span>Project</span>
            <select defaultValue={filters.project ?? ""} name="project">
              <option value="">All</option>
              {projects.map((project) => (
                <option key={project.slug} value={project.slug}>
                  {project.slug}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Area</span>
            <input defaultValue={filters.area ?? ""} name="area" placeholder="payments" />
          </label>
          <label>
            <span>Type</span>
            <input defaultValue={filters.doc_type ?? ""} name="doc_type" placeholder="runbook" />
          </label>
          <label>
            <span>Tag</span>
            <input defaultValue={filters.tag ?? ""} name="tag" placeholder="webhook" />
          </label>
          <label>
            <span>Status</span>
            <select defaultValue={filters.status ?? ""} name="status">
              <option value="">All</option>
              <option value="active">active</option>
              <option value="stale">stale</option>
              <option value="archived">archived</option>
            </select>
          </label>
          <button className="button" type="submit">
            Apply
          </button>
        </form>
        <div className="filter-summary">
          <span>{documents.length} shown</span>
          {areas.length > 0 ? <span>Areas: {areas.join(", ")}</span> : null}
          {docTypes.length > 0 ? <span>Types: {docTypes.join(", ")}</span> : null}
          {tags.length > 0 ? <span>Tags: {tags.slice(0, 8).join(", ")}</span> : null}
        </div>
      </section>
      <section className="section panel">
        {activeView === "graph" ? (
          <DocumentGraph
            detailHref={detailHref}
            documents={documents}
            project={filters.project}
          />
        ) : (
          <DocumentTable detailHref={detailHref} documents={documents} />
        )}
      </section>
    </>
  );
}

function unique(values: Array<string | null>) {
  return [...new Set(values.filter((value): value is string => Boolean(value)))].sort();
}

function documentsViewHref({
  baseHref,
  filters,
  hiddenFields,
  view,
}: {
  baseHref: string;
  filters: DocumentFilters;
  hiddenFields: Record<string, string>;
  view: DocumentViewMode;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(hiddenFields)) {
    if (value) {
      params.set(key, value);
    }
  }
  for (const [key, value] of Object.entries(filters)) {
    if (value) {
      params.set(key, value);
    }
  }
  params.set("view", view);
  return `${baseHref}?${params.toString()}`;
}
