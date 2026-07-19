"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { projectDraftToPayload, type ProjectDraft } from "@/lib/project-draft";

const emptyDraft: ProjectDraft = {
  name: "",
  slug: "",
  rootPath: "",
  description: "",
  parentSlug: "",
};

export function ProjectCreateForm() {
  const router = useRouter();
  const [draft, setDraft] = useState(emptyDraft);
  const [message, setMessage] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setMessage("");

    try {
      const response = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(projectDraftToPayload(draft)),
      });
      const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
      if (!response.ok) {
        throw new Error(payload?.detail ?? `Create failed: ${response.status}`);
      }
      setDraft(emptyDraft);
      setMessage("Project added. You can now sync its documents.");
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Create failed");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <details className="panel project-create-panel">
      <summary>Add project</summary>
      <form className="project-create-form" onSubmit={(event) => void submit(event)}>
        <label>
          Name
          <input
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            placeholder="Context Router"
            required
            value={draft.name}
          />
        </label>
        <label>
          Slug
          <input
            onChange={(event) => setDraft({ ...draft, slug: event.target.value })}
            placeholder="context-router"
            required
            value={draft.slug}
          />
        </label>
        <label className="project-create-wide">
          Project root path
          <input
            onChange={(event) => setDraft({ ...draft, rootPath: event.target.value })}
            placeholder="/Users/you/workspace/context-router"
            value={draft.rootPath}
          />
        </label>
        <label>
          Parent slug (optional)
          <input
            onChange={(event) => setDraft({ ...draft, parentSlug: event.target.value })}
            placeholder="workspace"
            value={draft.parentSlug}
          />
        </label>
        <label>
          Description
          <input
            onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            placeholder="What this project contains"
            value={draft.description}
          />
        </label>
        <div className="project-create-actions">
          <button className="button active" disabled={isSaving} type="submit">
            {isSaving ? "Adding…" : "Add project"}
          </button>
          {message ? <span aria-live="polite">{message}</span> : null}
        </div>
      </form>
    </details>
  );
}
