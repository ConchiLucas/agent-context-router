import {
  buildDocumentChildLayout,
  documentFilename,
  documentNodeLabel,
  shouldShowDocumentSubtreeAction,
} from "@/lib/document-tree";
import type { DocumentTreeNode } from "@/lib/types";

interface DocumentTreeProps {
  node: DocumentTreeNode;
  nodePath?: readonly number[];
  selectedId: string | null;
  onSelect: (node: DocumentTreeNode) => void;
  onOpenSubtree: (nodePath: readonly number[]) => void;
  callNumbersByDocumentId?: ReadonlyMap<string, number[]>;
}

export function DocumentTree({
  nodePath = [],
  ...props
}: DocumentTreeProps) {
  return (
    <DocumentTreeBranch
      {...props}
      nodePath={nodePath}
      depth={1}
      descendantsSuppressed={false}
    />
  );
}

interface DocumentTreeBranchProps
  extends Omit<DocumentTreeProps, "nodePath"> {
  nodePath: readonly number[];
  depth: number;
  descendantsSuppressed: boolean;
}

function DocumentTreeBranch({
  node,
  nodePath,
  depth,
  descendantsSuppressed,
  selectedId,
  onSelect,
  onOpenSubtree,
  callNumbersByDocumentId,
}: DocumentTreeBranchProps) {
  const callNumbers = callNumbersByDocumentId?.get(node.id) ?? [];
  const label = documentNodeLabel(node);
  const indexedChildren = node.children.map((child, index) => ({
    child,
    index,
  }));
  const childLayout = buildDocumentChildLayout(indexedChildren, depth);
  const showChildren =
    node.children.length > 0 && !descendantsSuppressed;
  const showSubtreeAction = shouldShowDocumentSubtreeAction(
    node,
    descendantsSuppressed,
  );
  const documentAriaLabel = [
    `查看文档：${label}`,
    callNumbers.length > 0
      ? `MCP 调用批次 ${callNumbers.join("、")}`
      : null,
    node.error ? `错误：${node.error}` : null,
  ]
    .filter(Boolean)
    .join("，");

  return (
    <li className="document-tree-item">
      <article
        className="document-node"
        data-selected={selectedId === node.id}
        data-error={Boolean(node.error)}
        data-has-call-numbers={callNumbers.length > 0}
      >
        <button
          type="button"
          className="document-node-main"
          aria-label={documentAriaLabel}
          disabled={node.selectable === false}
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
          <span>{label}</span>
          <code>{documentFilename(node.path)}</code>
          {node.error ? <small>{node.error}</small> : null}
        </button>

        {showSubtreeAction ? (
          <button
            type="button"
            className="document-subtree-button"
            aria-label={`查看“${label}”的 ${node.children.length} 个下级文档`}
            onClick={() => onOpenSubtree(nodePath)}
          >
            <span>{node.children.length} 个下级文档</span>
            <span aria-hidden="true">→</span>
          </button>
        ) : null}
      </article>

      {showChildren ? (
        <div
          className="document-children-rows"
          data-wrapped={childLayout.suppressRenderedChildDescendants}
        >
          {childLayout.rows.map((row, rowIndex) => (
            <ul className="document-tree-row" key={`row-${rowIndex}`}>
              {row.map(({ child, index }) => (
                <DocumentTreeBranch
                  key={`${child.id}-${index}`}
                  node={child}
                  nodePath={[...nodePath, index]}
                  depth={depth + 1}
                  descendantsSuppressed={
                    childLayout.suppressRenderedChildDescendants
                  }
                  selectedId={selectedId}
                  onSelect={onSelect}
                  onOpenSubtree={onOpenSubtree}
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
