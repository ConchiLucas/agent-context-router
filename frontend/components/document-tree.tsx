import type { DocumentTreeNode } from "@/lib/types";

interface DocumentTreeProps {
  node: DocumentTreeNode;
  selectedId: string | null;
  onSelect: (node: DocumentTreeNode) => void;
  callNumbersByDocumentId?: ReadonlyMap<string, number[]>;
}

function filename(path: string): string {
  return path.split("/").filter(Boolean).at(-1) ?? path;
}

function nodeLabel(node: DocumentTreeNode): string {
  if (node.relative_path === null) return "项目文档入口";
  if (filename(node.path).includes("subprojects-overview")) return "子项目总览";

  const projectName = /^`([^`]+)`[：:]/.exec(node.description);
  if (projectName) return projectName[1];

  const firstPhrase = node.description.split(/[，,；;]/)[0].trim();
  if (firstPhrase.length > 18) {
    return `${firstPhrase.slice(0, 18)}…`;
  }
  return firstPhrase;
}

function rowsOfFour(nodes: DocumentTreeNode[]): DocumentTreeNode[][] {
  const rows: DocumentTreeNode[][] = [];
  for (let index = 0; index < nodes.length; index += 4) {
    rows.push(nodes.slice(index, index + 4));
  }
  return rows;
}

export function DocumentTree({
  node,
  selectedId,
  onSelect,
  callNumbersByDocumentId,
}: DocumentTreeProps) {
  const callNumbers = callNumbersByDocumentId?.get(node.id) ?? [];

  return (
    <li className="document-tree-item">
      <button
        type="button"
        className="document-node"
        data-selected={selectedId === node.id}
        data-error={Boolean(node.error)}
        data-has-call-numbers={callNumbers.length > 0}
        onClick={() => onSelect(node)}
        title={node.description}
      >
        {callNumbers.length > 0 ? (
          <span className="document-call-badges" aria-label="MCP 调用批次">
            {callNumbers.map((callNumber) => (
              <span
                className="document-call-badge"
                aria-label={`第 ${callNumber} 次 MCP 调用`}
                key={callNumber}
              >
                {callNumber}
              </span>
            ))}
          </span>
        ) : null}
        <span>{nodeLabel(node)}</span>
        <code>{filename(node.path)}</code>
        {node.error ? <small>{node.error}</small> : null}
      </button>

      {node.children.length > 0 ? (
        <div className="document-children-rows">
          {rowsOfFour(node.children).map((row, rowIndex) => (
            <ul className="document-tree-row" key={`row-${rowIndex}`}>
              {row.map((child, index) => (
                <DocumentTree
                  key={`${child.id}-${index}`}
                  node={child}
                  selectedId={selectedId}
                  onSelect={onSelect}
                  callNumbersByDocumentId={callNumbersByDocumentId}
                />
              ))}
            </ul>
          ))}
        </div>
      ) : null}
    </li>
  );
}
