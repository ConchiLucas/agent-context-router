import type { ReactNode } from "react";

import { MarkdownContent } from "@/components/markdown-content";
import type { DocumentDetail } from "@/lib/types";

type DocumentDetailContentProps = Readonly<{
  closeControl?: ReactNode;
  document: DocumentDetail;
}>;

export function DocumentDetailContent({
  closeControl,
  document,
}: DocumentDetailContentProps) {
  return (
    <>
      <header className="document-detail-header">
        {closeControl}
        <h1 className="page-title">{document.title}</h1>
        <p className="document-detail-id">{document.id}</p>
      </header>

      <section className="section panel document-detail-summary">
        <div>
          <h2 className="section-title">Metadata</h2>
          <DocumentMetadata document={document} />
        </div>
        <div className="document-detail-command">
          <h2 className="section-title">MCP Document ID</h2>
          <pre style={commandBlockStyle}>{document.id}</pre>
        </div>
      </section>

      <section className="section panel">
        <h2 className="section-title">Content</h2>
        <MarkdownContent content={document.content_markdown} />
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
