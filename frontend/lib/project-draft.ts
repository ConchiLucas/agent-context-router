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
  if (!name || !slug) {
    throw new Error("Name and slug are required");
  }

  return {
    name,
    slug,
    root_path: optionalValue(draft.rootPath),
    description: draft.description.trim(),
    parent_slug: optionalValue(draft.parentSlug),
  };
}

function optionalValue(value: string) {
  return value.trim() || null;
}
