import type { ProjectKind } from "@/lib/types";

export function projectDirectoryName(relativePath: string): string | null {
  const normalized = relativePath.trim().replace(/\/+$/, "");
  if (!normalized || normalized === ".") return null;
  return normalized.split("/").filter(Boolean).at(-1) ?? null;
}

export function suggestProjectDocumentRelativePath(
  projectKind: ProjectKind,
  relativePath: string,
): string {
  const directoryName = projectDirectoryName(relativePath);
  return directoryName
    ? `docs/${projectKind}/${directoryName}/AGENTS.md`
    : "";
}
