import type { DocumentTreeNode } from "@/lib/types";

interface DocumentTreeProps {
  node: DocumentTreeNode;
  selectedId: string | null;
  onSelect: (node: DocumentTreeNode) => void;
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

export function DocumentTree({
  node,
  selectedId,
  onSelect,
}: DocumentTreeProps) {
  return (
    <li>
      <button
        type="button"
        className="document-node"
        data-selected={selectedId === node.id}
        data-error={Boolean(node.error)}
        onClick={() => onSelect(node)}
        title={node.description}
      >
        <span>{nodeLabel(node)}</span>
        <code>{filename(node.path)}</code>
        {node.error ? <small>{node.error}</small> : null}
      </button>

      {node.children.length > 0 ? (
        <ul>
          {node.children.map((child, index) => (
            <DocumentTree
              key={`${child.id}-${index}`}
              node={child}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}
