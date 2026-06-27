import { DocumentTable } from "@/components/document-table";
import { getDocuments, getProjects } from "@/lib/api";

type DocumentsPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function DocumentsPage({ searchParams }: DocumentsPageProps) {
  const params = await searchParams;
  const filters = {
    project: singleValue(params.project),
    area: singleValue(params.area),
    doc_type: singleValue(params.doc_type),
    tag: singleValue(params.tag),
    status: singleValue(params.status),
  };

  const [documentsResult, projectsResult] = await Promise.allSettled([
    getDocuments(filters),
    getProjects(),
  ]);
  const documents =
    documentsResult.status === "fulfilled" ? documentsResult.value.documents : [];
  const projects = projectsResult.status === "fulfilled" ? projectsResult.value.projects : [];
  const areas = unique(documents.map((document) => document.area).filter(Boolean));
  const docTypes = unique(documents.map((document) => document.doc_type));
  const tags = unique(documents.flatMap((document) => document.tags));

  return (
    <>
      <header>
        <h1 className="page-title">Documents</h1>
        <p className="page-subtitle">Context documents and routing metadata.</p>
      </header>
      <section className="section panel">
        <form className="filter-grid">
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
        <DocumentTable documents={documents} />
      </section>
    </>
  );
}

function singleValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function unique(values: Array<string | null>) {
  return [...new Set(values.filter((value): value is string => Boolean(value)))].sort();
}
