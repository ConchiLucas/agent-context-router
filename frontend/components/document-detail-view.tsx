import Link from "next/link";

import { getDocument } from "@/lib/api";
import type { DocumentDetail } from "@/lib/types";

type DocumentDetailViewProps = Readonly<{
  documentId: string;
  backHref: string;
  backLabel?: string;
  showInlineBack?: boolean;
}>;

export async function DocumentDetailView({
  documentId,
  backHref,
  backLabel = "Documents",
  showInlineBack = true,
}: DocumentDetailViewProps) {
  const result = await Promise.allSettled([getDocument(documentId)]);
  const document = result[0].status === "fulfilled" ? result[0].value : null;

  if (document === null) {
    return (
      <section className="panel">
        <h1 className="page-title">Document unavailable</h1>
        <p className="page-subtitle">{documentId}</p>
        <Link className="button" href={backHref} style={{ display: "inline-flex", marginTop: "1rem" }}>
          Back
        </Link>
      </section>
    );
  }

  return (
    <>
      <header className="document-detail-header">
        {showInlineBack ? (
          <Link className="document-detail-back" href={backHref}>
            {backLabel}
          </Link>
        ) : null}
        <h1 className="page-title">{document.title}</h1>
        <p className="document-detail-id">{document.id}</p>
      </header>

      <section className="section panel document-detail-summary">
        <div>
          <h2 className="section-title">Metadata</h2>
          <DocumentMetadata document={document} />
        </div>
        <div className="document-detail-command">
          <h2 className="section-title">Read Command</h2>
          <pre style={commandBlockStyle}>
{`ctx read ${document.id} --trace <trace-id> --reason "<why needed>"`}
          </pre>
        </div>
      </section>

      <section className="section panel">
        <h2 className="section-title">Content</h2>
        <pre style={contentBlockStyle}>{document.content_markdown}</pre>
      </section>
    </>
  );
}

function DocumentMetadata({ document }: Readonly<{ document: DocumentDetail }>) {
  const items = [
    ["Type", document.doc_type],
    ["Area", document.area ?? "general"],
    ["Status", document.status],
    ["Source", document.source_path],
    ["Tags", document.tags.length > 0 ? document.tags.join(", ") : "none"],
  ];

  return (
    <div className="document-detail-meta-grid">
      {items.map(([label, value]) => (
        <div className="document-detail-meta-item" key={label}>
          <strong>{label}</strong>
          <span title={value}>{value}</span>
        </div>
      ))}
    </div>
  );
}

const commandBlockStyle = {
  margin: 0,
  overflowX: "auto",
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
  border: "1px solid var(--line)",
  borderRadius: "var(--radius-md)",
  background: "rgba(2, 6, 23, 0.55)",
  color: "#cbd5e1",
  padding: "0.8rem",
  fontSize: "0.8rem",
  lineHeight: 1.5,
} as const;

const contentBlockStyle = {
  margin: 0,
  maxHeight: "70vh",
  overflow: "auto",
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
  border: "1px solid var(--line)",
  borderRadius: "var(--radius-md)",
  background: "rgba(2, 6, 23, 0.55)",
  color: "#dbeafe",
  padding: "1.15rem",
  fontSize: "0.86rem",
  lineHeight: 1.7,
} as const;
