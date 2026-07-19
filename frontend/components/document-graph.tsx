import Link from "next/link";

import type { DocumentSummary } from "@/lib/types";

type DocumentGraphProps = Readonly<{
  documents: DocumentSummary[];
  detailHref?: (document: DocumentSummary) => string;
  project?: string;
}>;

type LinkedDocument = Readonly<{
  document: DocumentSummary;
  label: string;
}>;

type GraphRoute = Readonly<{
  id: string;
  relation: string;
  branchDocument: DocumentSummary;
  documents: LinkedDocument[];
}>;

export function DocumentGraph({
  documents,
  detailHref = (document) => `/documents/${encodeURIComponent(document.id)}`,
  project,
}: DocumentGraphProps) {
  if (documents.length === 0) {
    return (
      <p className="page-subtitle" style={{ padding: "2rem", textAlign: "center" }}>
        No documents indexed yet.
      </p>
    );
  }

  const documentById = new Map(documents.map((document) => [document.id, document]));
  const rootDocument = pickRootDocument(documents, project);
  const rootLinks = rootDocument ? linkedDocuments(rootDocument, documentById) : [];
  const routes = rootLinks.map((link) => ({
    id: `${rootDocument?.id ?? "root"}-${link.document.id}`,
    relation: link.label,
    branchDocument: link.document,
    documents: linkedDocuments(link.document, documentById),
  }));
  const unlinkedDocuments = rootDocument
    ? documents.filter((document) => document.id !== rootDocument.id && !isConnected(document, routes))
    : documents;

  return (
    <div className="document-graph-map">
      <div className="document-graph-root">
        {rootDocument ? (
          <DocumentGraphNode
            childCount={rootLinks.length}
            command={readCommand(rootDocument.id)}
            description="AI 先读总入口，再按 Markdown 链接选择下一层 doc-id。"
            detailHref={detailHref}
            document={rootDocument}
            label="总入口"
            variant="root-node"
          />
        ) : (
          <div className="document-graph-node root-node">
            <span className="document-graph-node-label">总索引文档</span>
            <strong>等待建立总入口</strong>
            <span>建议补齐带 doc_id 的 AGENTS.md 或 AI_CONTEXT_INDEX.md。</span>
          </div>
        )}
      </div>

      <div className="document-graph-routes">
        {routes.length > 0 ? (
          routes.map((route) => (
            <section className="document-graph-route" key={route.id}>
              <DocumentGraphNode
                childCount={route.documents.length}
                command={readCommand(route.branchDocument.id)}
                description={descriptionForDocument(route.branchDocument)}
                detailHref={detailHref}
                document={route.branchDocument}
                label={route.relation}
                variant="branch-node"
              />
              {route.documents.length > 0 ? (
                <>
                  <div className="document-graph-connector" aria-hidden="true" />
                  <div className="document-graph-leaf-column">
                    <div className="document-graph-leaves-title">
                      <span>下一层文档</span>
                      <strong>{route.documents.length}</strong>
                    </div>
                    <div className="document-graph-leaves">
                      {route.documents.map((linkedDocument) => (
                        <DocumentGraphNode
                          command={readCommand(linkedDocument.document.id)}
                          description={descriptionForDocument(linkedDocument.document)}
                          detailHref={detailHref}
                          document={linkedDocument.document}
                          key={`${route.id}-${linkedDocument.document.id}`}
                          label={linkedDocument.label}
                        />
                      ))}
                    </div>
                  </div>
                </>
              ) : null}
            </section>
          ))
        ) : (
          <div className="document-graph-empty panel">
            <h2 className="section-title">没有解析到下一层链接</h2>
            <p className="page-subtitle">
              在总入口 Markdown 中添加本地链接，例如
              {" "}
              <code>[数据库信息](./rob-english-word-workforce-database-info.md)</code>
              ，然后在 Projects 页面点击 Sync Documents。
            </p>
          </div>
        )}

        {unlinkedDocuments.length > 0 ? (
          <section className="document-graph-route">
            <DocumentGraphNode
              childCount={unlinkedDocuments.length}
              command={readCommand(unlinkedDocuments[0].id)}
              description="这些文档已入库，但还没有被总入口或下一层文档链接到。"
              detailHref={detailHref}
              document={unlinkedDocuments[0]}
              label="未关联文档"
              variant="branch-node"
            />
            {unlinkedDocuments.length > 1 ? (
              <>
                <div className="document-graph-connector" aria-hidden="true" />
                <div className="document-graph-leaf-column">
                  <div className="document-graph-leaves-title">
                    <span>待补链接</span>
                    <strong>{unlinkedDocuments.length - 1}</strong>
                  </div>
                  <div className="document-graph-leaves">
                    {unlinkedDocuments.slice(1).map((document) => (
                      <DocumentGraphNode
                        command={readCommand(document.id)}
                        description={descriptionForDocument(document)}
                        detailHref={detailHref}
                        document={document}
                        key={`unlinked-${document.id}`}
                      />
                    ))}
                  </div>
                </div>
              </>
            ) : null}
          </section>
        ) : null}
      </div>
    </div>
  );
}

function DocumentGraphNode({
  childCount,
  command,
  description,
  detailHref,
  document,
  label,
  variant,
}: Readonly<{
  childCount?: number;
  command?: string;
  description?: string;
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
      <span>{document.id}</span>
      {description ? (
        <small className="document-graph-node-description">{description}</small>
      ) : null}
      <div className="document-graph-node-meta">
        <small>{document.project_slug}</small>
        {childCount !== undefined ? <small>下一步 {childCount}</small> : null}
      </div>
      {command ? <code className="document-graph-node-command">{command}</code> : null}
    </Link>
  );
}

function pickRootDocument(documents: DocumentSummary[], project?: string) {
  const agentDocuments = documents.filter((document) => document.doc_type === "agent_index");
  return (
    agentDocuments.find((document) => project && document.project_slug === project) ??
    agentDocuments.find((document) => document.project_slug.includes("workforce")) ??
    agentDocuments[0] ??
    documents[0] ??
    null
  );
}

function linkedDocuments(
  document: DocumentSummary,
  documentById: Map<string, DocumentSummary>
): LinkedDocument[] {
  return (document.links ?? [])
    .filter((link) => link.target_document_id !== null)
    .sort((left, right) => left.sort_order - right.sort_order)
    .map((link) => {
      const targetDocument = documentById.get(link.target_document_id ?? "");
      if (!targetDocument) {
        return null;
      }
      return {
        document: targetDocument,
        label: link.label,
      };
    })
    .filter((link): link is LinkedDocument => link !== null);
}

function isConnected(document: DocumentSummary, routes: GraphRoute[]) {
  return routes.some(
    (route) =>
      route.branchDocument.id === document.id ||
      route.documents.some((linkedDocument) => linkedDocument.document.id === document.id)
  );
}

function labelForDocument(document: DocumentSummary) {
  return docTypeLabels[document.doc_type] ?? document.doc_type;
}

function descriptionForDocument(document: DocumentSummary) {
  if (document.doc_type === "agent_index") {
    return "AI 入口索引，说明下一层文档和读取方式。";
  }
  if (document.doc_type === "subprojects_overview") {
    return "大项目下的子项目清单和职责入口。";
  }
  if (document.doc_type === "project_overview") {
    return "子项目作用、用途和主要功能概览。";
  }
  if (document.doc_type === "database_info") {
    return "数据库连接、库名账号、端口和排查入口。";
  }
  if (document.doc_type === "flow_overview") {
    return "项目间调用方向、数据流转和排查路径总览。";
  }
  return "稳定说明文档，摘要不足时再读取全文。";
}

function readCommand(documentId: string) {
  return `document_id: ${documentId}`;
}

const docTypeLabels: Record<string, string> = {
  agent_index: "AI 入口",
  database_info: "数据库信息",
  flow_overview: "链路流转",
  project_overview: "项目概览",
  subprojects_overview: "子项目总览",
};
