import Link from "next/link";

import { groupDocumentsByDepth } from "@/lib/document-health";
import type { DocumentSummary } from "@/lib/types";

type DocumentGraphProps = Readonly<{
  documents: DocumentSummary[];
  detailHref?: (document: DocumentSummary) => string;
  project?: string;
}>;

export function DocumentGraph({
  documents,
  detailHref = (document) => `/documents/${encodeURIComponent(document.id)}`,
}: DocumentGraphProps) {
  if (documents.length === 0) {
    return (
      <p className="page-subtitle document-health-empty">
        No documents indexed yet.
      </p>
    );
  }

  const { levels, orphans, brokenLinks } = groupDocumentsByDepth(documents);

  return (
    <div className="document-health-map">
      <div className="document-depth-levels">
        {levels.map((level) => (
          <section className="document-depth-level" key={level.depth}>
            <div className="document-health-heading">
              <div>
                <span>Reachable from AGENTS.md</span>
                <h3>Level {level.depth}</h3>
              </div>
              <strong>{level.documents.length}</strong>
            </div>
            <div className="document-depth-nodes">
              {level.documents.map((document) => (
                <DocumentGraphNode
                  detailHref={detailHref}
                  document={document}
                  key={document.id}
                />
              ))}
            </div>
          </section>
        ))}
      </div>

      {orphans.length > 0 ? (
        <section className="document-health-section orphan-section">
          <div className="document-health-heading">
            <div>
              <span>Not reachable from AGENTS.md</span>
              <h3>Orphan documents</h3>
            </div>
            <strong>{orphans.length}</strong>
          </div>
          <div className="document-depth-nodes">
            {orphans.map((document) => (
              <DocumentGraphNode
                detailHref={detailHref}
                document={document}
                key={document.id}
                variant="orphan-node"
              />
            ))}
          </div>
        </section>
      ) : null}

      {brokenLinks.length > 0 ? (
        <section className="document-health-section broken-section">
          <div className="document-health-heading">
            <div>
              <span>Markdown target could not be resolved</span>
              <h3>Broken links</h3>
            </div>
            <strong>{brokenLinks.length}</strong>
          </div>
          <div className="broken-link-list">
            {brokenLinks.map(({ source, link }) => (
              <article
                className="broken-link-item"
                key={`${source.id}-${link.sort_order}-${link.target_path}`}
              >
                <div>
                  <strong>{link.label || link.target_path}</strong>
                  <span>from {source.title}</span>
                </div>
                <code>{link.target_path}</code>
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function DocumentGraphNode({
  detailHref,
  document,
  variant,
}: Readonly<{
  detailHref: (document: DocumentSummary) => string;
  document: DocumentSummary;
  variant?: string;
}>) {
  const linkedCount = document.links.filter((link) => !link.is_broken).length;
  return (
    <Link
      aria-label={`Preview document ${document.title}`}
      className={`document-graph-node ${variant ?? "reachable-node"}`}
      href={detailHref(document)}
    >
      <span className="document-graph-node-header">
        <span className="document-graph-node-label">{labelForDocument(document)}</span>
        <span className="document-graph-node-preview">Preview</span>
      </span>
      <strong>{document.title}</strong>
      <span>{document.source_path}</span>
      <div className="document-graph-node-meta">
        <small>{document.id}</small>
        <small>{linkedCount} next links</small>
      </div>
      <code className="document-graph-node-command">document_id: {document.id}</code>
    </Link>
  );
}

function labelForDocument(document: DocumentSummary) {
  return document.doc_type === "agent_index" ? "Entry" : document.doc_type;
}
