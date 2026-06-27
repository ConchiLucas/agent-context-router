import type { DocumentSummary } from "@/lib/types";

export function DocumentTable({ documents }: Readonly<{ documents: DocumentSummary[] }>) {
  if (documents.length === 0) {
    return <p className="page-subtitle">No documents indexed yet.</p>;
  }

  return (
    <table className="table">
      <thead>
        <tr>
          <th>ID</th>
          <th>Project</th>
          <th>Area</th>
          <th>Type</th>
          <th>Chunks</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {documents.map((document) => (
          <tr key={document.id}>
            <td>
              <strong>{document.title}</strong>
              <div className="page-subtitle">{document.id}</div>
            </td>
            <td>{document.project_slug}</td>
            <td>{document.area ?? "general"}</td>
            <td>{document.doc_type}</td>
            <td>{document.chunk_count}</td>
            <td>
              <span className="badge">{document.status}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
