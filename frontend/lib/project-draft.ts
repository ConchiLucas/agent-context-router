export type ProjectDraft = {
  name: string;
  slug: string;
  rootPath: string;
  description: string;
  parentSlug: string;
};

export function projectDraftToPayload(draft: ProjectDraft) {
  const name = draft.name.trim();
  const slug = draft.slug.trim();
  const rootPath = draft.rootPath.trim();
  if (!name || !slug) {
    throw new Error("Name and slug are required");
  }
  if (!rootPath) {
    throw new Error("Project root path is required");
  }

  return {
    name,
    slug,
    root_path: rootPath,
    description: draft.description.trim(),
    parent_slug: optionalValue(draft.parentSlug),
  };
}

function optionalValue(value: string) {
  return value.trim() || null;
}
