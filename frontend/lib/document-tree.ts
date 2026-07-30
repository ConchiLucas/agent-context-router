import type { DocumentTreeNode } from "@/lib/types";

export const MAX_DOCUMENT_CHILDREN_PER_ROW = 4;

export interface DocumentChildLayout<T> {
  rows: T[][];
  suppressRenderedChildDescendants: boolean;
}

export function documentFilename(path: string): string {
  return path.split("/").filter(Boolean).at(-1) ?? path;
}

export function documentNodeLabel(node: DocumentTreeNode): string {
  if (
    node.relative_path === null &&
    node.description === "工作空间文档入口"
  ) {
    return "工作空间文档入口";
  }
  if (node.relative_path === null) return "项目文档入口";
  if (documentFilename(node.path).includes("subprojects-overview")) {
    return "子项目总览";
  }

  const projectName = /^`([^`]+)`[：:]/.exec(node.description);
  if (projectName) return projectName[1];

  const firstPhrase = node.description.split(/[，,；;]/)[0].trim();
  if (firstPhrase.length > 18) {
    return `${firstPhrase.slice(0, 18)}…`;
  }
  return firstPhrase;
}

export function buildDocumentChildLayout<T>(
  children: readonly T[],
  parentDepth: number,
): DocumentChildLayout<T> {
  if (children.length === 0) {
    return {
      rows: [],
      suppressRenderedChildDescendants: false,
    };
  }

  // A local root is depth 1, so only its second level is exempt from wrapping.
  const suppressRenderedChildDescendants =
    parentDepth >= 2 && children.length > MAX_DOCUMENT_CHILDREN_PER_ROW;

  if (!suppressRenderedChildDescendants) {
    return {
      rows: [Array.from(children)],
      suppressRenderedChildDescendants,
    };
  }

  const rows: T[][] = [];
  for (
    let index = 0;
    index < children.length;
    index += MAX_DOCUMENT_CHILDREN_PER_ROW
  ) {
    rows.push(
      Array.from(
        children.slice(index, index + MAX_DOCUMENT_CHILDREN_PER_ROW),
      ),
    );
  }

  return {
    rows,
    suppressRenderedChildDescendants,
  };
}

export function shouldShowDocumentSubtreeAction(
  node: DocumentTreeNode,
  descendantsSuppressed: boolean,
): boolean {
  return descendantsSuppressed && node.children.length > 0;
}

export function resolveDocumentPath(
  root: DocumentTreeNode,
  childIndexes: readonly number[],
): DocumentTreeNode[] | null {
  const path = [root];
  let current = root;

  for (const childIndex of childIndexes) {
    if (
      !Number.isInteger(childIndex) ||
      childIndex < 0 ||
      childIndex >= current.children.length
    ) {
      return null;
    }
    current = current.children[childIndex];
    path.push(current);
  }

  return path;
}

export function retainDocumentTreePaths(
  node: DocumentTreeNode,
  includedDocumentIds: ReadonlySet<string>,
): DocumentTreeNode | null {
  const children = node.children
    .map((child) => retainDocumentTreePaths(child, includedDocumentIds))
    .filter((child): child is DocumentTreeNode => child !== null);

  if (!includedDocumentIds.has(node.id) && children.length === 0) {
    return null;
  }

  return {
    ...node,
    children,
  };
}
