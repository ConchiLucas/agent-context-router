import type { DocumentSummary } from "@/lib/types";
import Link from "next/link";

const statusClassMap: Record<string, string> = {
  active: "badge-active",
  stale: "badge-stale",
  archived: "badge-archived",
};

type DocumentTableProps = Readonly<{
  documents: DocumentSummary[];
  detailHref?: (document: DocumentSummary) => string;
}>;

export function DocumentTable({
  documents,
  detailHref = (document) => `/documents/${encodeURIComponent(document.id)}`,
}: DocumentTableProps) {
  if (documents.length === 0) {
    return <p className="page-subtitle" style={{ textAlign: "center", padding: "2rem" }}>No documents indexed yet.</p>;
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table className="table">
        <thead>
          <tr>
            <th style={{ borderTopLeftRadius: "var(--radius-md)" }}>Document</th>
            <th>Project</th>
            <th>Area</th>
            <th>Type</th>
            <th>Reachability</th>
            <th>Depth</th>
            <th>Broken links</th>
            <th style={{ borderTopRightRadius: "var(--radius-md)", width: "100px" }}>Status</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((document) => (
            <tr key={document.id}>
              <td style={{ minWidth: "220px" }}>
                <Link
                  href={detailHref(document)}
                  style={{ display: "block", color: "#f1f5f9", fontSize: "0.92rem", fontWeight: 600 }}
                >
                  {document.title}
                </Link>
                <span className="page-subtitle" style={{ fontSize: "0.75rem", fontFamily: "ui-monospace, monospace", opacity: 0.8 }}>
                  {document.id}
                </span>
              </td>
              <td>
                <span className="badge" style={{ fontSize: "0.75rem", letterSpacing: "0.02em" }}>
                  {document.project_slug}
                </span>
              </td>
              <td>
                <span style={{ fontSize: "0.9rem", color: "#cbd5e1" }}>
                  {document.area ?? "general"}
                </span>
              </td>
              <td>
                <span style={{ fontSize: "0.9rem", color: "#cbd5e1" }}>
                  {document.doc_type}
                </span>
              </td>
              <td>
                <span className={`badge ${document.is_reachable ? "badge-active" : "badge-stale"}`}>
                  {document.is_reachable ? "reachable" : "orphan"}
                </span>
              </td>
              <td>{document.graph_depth ?? "—"}</td>
              <td>{document.broken_link_count}</td>
              <td>
                <span className={`badge ${statusClassMap[document.status] || ""}`}>
                  {document.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
