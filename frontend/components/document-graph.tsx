import Link from "next/link";

import {
  buildDocumentHierarchy,
  groupDocumentsByDepth,
  type DocumentHierarchyNode,
} from "@/lib/document-health";
import type { DocumentSummary } from "@/lib/types";

type DocumentGraphProps = Readonly<{
  documents: DocumentSummary[];
  detailHref?: (document: DocumentSummary) => string;
  project?: string;
}>;

export function DocumentGraph({
  documents,
  detailHref = (document) => `/documents/${encodeURIComponent(document.id)}`,
  project,
}: DocumentGraphProps) {
  if (documents.length === 0) {
    return <p className="page-subtitle document-health-empty">No documents indexed yet.</p>;
  }

  const hierarchy = buildDocumentHierarchy(documents, project);
  const { orphans, brokenLinks } = groupDocumentsByDepth(documents);

  return (
    <div className="document-health-map">
      {hierarchy ? (
        <div className="document-hierarchy-scroll">
          <div className="document-hierarchy-tree">
            <DocumentTreeBranch
              detailHref={detailHref}
              keyPath={hierarchy.document.id}
              node={hierarchy}
            />
          </div>
        </div>
      ) : (
        <div className="document-graph-empty panel">
          <h2 className="section-title">等待建立 AGENTS.md 入口</h2>
          <p className="page-subtitle">同步映射目录后，入口和下一层链接会显示在这里。</p>
        </div>
      )}

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
                label="未关联文档"
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

function DocumentTreeBranch({
  detailHref,
  keyPath,
  node,
}: Readonly<{
  detailHref: (document: DocumentSummary) => string;
  keyPath: string;
  node: DocumentHierarchyNode;
}>) {
  const depth = node.document.graph_depth ?? 1;
  const variant = node.isReference
    ? "reference-node"
    : depth === 1
      ? "root-node"
      : node.children.length > 0
        ? "branch-node"
        : "leaf-node";
  const label = node.isReference
    ? `${node.edgeLabel ?? labelForDocument(node.document)} · 引用`
    : node.edgeLabel ?? "总入口";

  return (
    <div className="document-hierarchy-branch">
      <DocumentGraphNode
        childCount={node.isReference ? undefined : node.children.length}
        detailHref={detailHref}
        document={node.document}
        label={label}
        variant={variant}
      />
      {node.children.length > 0 ? (
        <>
          <div className="document-hierarchy-connector" aria-hidden="true" />
          <div className="document-hierarchy-children">
            {node.children.map((child, index) => {
              const childKey = `${keyPath}-${child.document.id}-${index}`;
              return (
                <div className="document-hierarchy-child" key={childKey}>
                  <DocumentTreeBranch
                    detailHref={detailHref}
                    keyPath={childKey}
                    node={child}
                  />
                </div>
              );
            })}
          </div>
        </>
      ) : null}
    </div>
  );
}

function DocumentGraphNode({
  childCount,
  detailHref,
  document,
  label,
  variant,
}: Readonly<{
  childCount?: number;
  detailHref: (document: DocumentSummary) => string;
  document: DocumentSummary;
  label?: string;
  variant?: string;
}>) {
  return (
    <Link
      aria-label={`预览文档 ${document.title}`}
      className={`document-graph-node ${variant ?? "leaf-node"}`}
      href={detailHref(document)}
      title={`预览 ${document.title}`}
    >
      <span className="document-graph-node-header">
        <span className="document-graph-node-label">{label ?? labelForDocument(document)}</span>
        <span className="document-graph-node-preview">预览</span>
      </span>
      <strong>{document.title}</strong>
      <span>{document.source_path}</span>
      <div className="document-graph-node-meta">
        <small>{document.id}</small>
        {childCount !== undefined ? <small>下一步 {childCount}</small> : null}
      </div>
      <code className="document-graph-node-command">document_id: {document.id}</code>
    </Link>
  );
}

function labelForDocument(document: DocumentSummary) {
  return document.doc_type === "agent_index" ? "AI 入口" : document.doc_type;
}
