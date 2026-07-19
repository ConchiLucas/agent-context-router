"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ProjectLinkReloadButton } from "@/components/project-link-reload-button";
import type {
  DocumentMappingCandidate,
  DocumentMappingCandidateListResponse,
  DocumentMappingResponse,
  ProjectSummary,
} from "@/lib/types";

type MappingState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "choosing" }
  | { status: "saving"; docsPath: string }
  | { status: "error"; message: string };

type ProjectDocumentControlsProps = Readonly<{
  project: ProjectSummary;
}>;

export function ProjectDocumentControls({ project }: ProjectDocumentControlsProps) {
  const router = useRouter();
  const [mappingState, setMappingState] = useState<MappingState>({ status: "idle" });
  const [candidates, setCandidates] = useState<DocumentMappingCandidate[]>([]);
  const [selectedPath, setSelectedPath] = useState(project.docs_path ?? "");
  const [notice, setNotice] = useState("");
  const chooserOpen = mappingState.status !== "idle";

  async function openChooser() {
    setMappingState({ status: "loading" });
    setNotice("");
    try {
      const response = await fetch("/api/document-mappings/candidates", { cache: "no-store" });
      const payload = (await response.json().catch(() => null)) as
        | DocumentMappingCandidateListResponse
        | { detail?: string }
        | null;
      if (!response.ok || !payload || !("candidates" in payload)) {
        throw new Error(
          payload && "detail" in payload && payload.detail
            ? payload.detail
            : `Could not load mappings: ${response.status}`,
        );
      }
      setCandidates(payload.candidates);
      const firstAvailable = payload.candidates.find(
        (candidate) =>
          !candidate.mapped_project_slug || candidate.mapped_project_slug === project.slug,
      );
      setSelectedPath(project.docs_path ?? firstAvailable?.docs_path ?? "");
      setMappingState({ status: "choosing" });
    } catch (error) {
      setMappingState({
        status: "error",
        message: error instanceof Error ? error.message : "Could not load mappings",
      });
    }
  }

  async function saveMapping() {
    if (!selectedPath) return;
    setMappingState({ status: "saving", docsPath: selectedPath });
    try {
      const response = await fetch(
        `/api/projects/${encodeURIComponent(project.slug)}/document-mapping`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ docs_path: selectedPath }),
        },
      );
      const payload = (await response.json().catch(() => null)) as
        | DocumentMappingResponse
        | { detail?: string }
        | null;
      if (!response.ok) {
        throw new Error(
          payload && "detail" in payload && payload.detail
            ? payload.detail
            : `Could not save mapping: ${response.status}`,
        );
      }
      setMappingState({ status: "idle" });
      setNotice("Mapping saved. Sync required.");
      router.refresh();
    } catch (error) {
      setMappingState({
        status: "error",
        message: error instanceof Error ? error.message : "Could not save mapping",
      });
    }
  }

  const saving = mappingState.status === "saving";
  const syncDisabled = !project.docs_path || project.mapping_status === "invalid";

  return (
    <div className="project-document-controls">
      <div className="project-document-actions">
        <button className="button" onClick={() => void openChooser()} type="button">
          {project.docs_path ? "Change Mapping" : "Map Documents"}
        </button>
        <ProjectLinkReloadButton
          disabled={syncDisabled}
          disabledReason={
            project.mapping_status === "invalid"
              ? "The mapped directory is invalid"
              : "Map a document directory first"
          }
          projectSlug={project.slug}
        />
      </div>

      {chooserOpen ? (
        <div className="project-mapping-chooser">
          {mappingState.status === "loading" ? (
            <span className="project-sync-status">Loading directories…</span>
          ) : (
            <>
              <label>
                <span>Document directory</span>
                <select
                  disabled={saving}
                  onChange={(event) => setSelectedPath(event.target.value)}
                  value={selectedPath}
                >
                  <option value="">Select a directory</option>
                  {candidates.map((candidate) => {
                    const occupiedByOther =
                      candidate.mapped_project_slug !== null &&
                      candidate.mapped_project_slug !== project.slug;
                    return (
                      <option
                        disabled={occupiedByOther}
                        key={candidate.docs_path}
                        value={candidate.docs_path}
                      >
                        {candidate.docs_path} · {candidate.markdown_count} docs
                        {occupiedByOther ? ` · used by ${candidate.mapped_project_slug}` : ""}
                      </option>
                    );
                  })}
                </select>
              </label>
              <div className="project-mapping-buttons">
                <button
                  className="button active"
                  disabled={!selectedPath || saving}
                  onClick={() => void saveMapping()}
                  type="button"
                >
                  {saving ? "Saving…" : "Save Mapping"}
                </button>
                <button
                  className="button"
                  disabled={saving}
                  onClick={() => setMappingState({ status: "idle" })}
                  type="button"
                >
                  Cancel
                </button>
              </div>
              {mappingState.status === "error" && mappingState.message ? (
                <span className="project-sync-status error">{mappingState.message}</span>
              ) : null}
            </>
          )}
        </div>
      ) : null}
      {notice ? <span className="project-sync-status success">{notice}</span> : null}
    </div>
  );
}
