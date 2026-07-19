"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { DocumentSyncResponse } from "@/lib/types";

type SyncState =
  | {
      status: "idle" | "loading";
      message: string;
    }
  | {
      status: "success" | "error";
      message: string;
    };

type ProjectLinkReloadButtonProps = Readonly<{
  disabled?: boolean;
  projectSlug: string;
}>;

export function ProjectLinkReloadButton({
  disabled = false,
  projectSlug,
}: ProjectLinkReloadButtonProps) {
  const router = useRouter();
  const [syncState, setSyncState] = useState<SyncState>({
    status: "idle",
    message: "",
  });
  const isLoading = syncState.status === "loading";
  const isDisabled = disabled || isLoading;

  async function reloadLinks() {
    setSyncState({
      status: "loading",
      message: "Syncing local docs",
    });

    try {
      const response = await fetch(
        `/api/projects/${encodeURIComponent(projectSlug)}/documents/sync-local`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            docs_dir: ".",
            prune: true,
          }),
        },
      );
      const payload = (await response.json().catch(() => null)) as
        | DocumentSyncResponse
        | { detail?: string }
        | null;

      if (!response.ok) {
        throw new Error(
          payload && "detail" in payload && payload.detail
            ? payload.detail
            : `Sync failed: ${response.status}`,
        );
      }

      const result = payload as DocumentSyncResponse;
      setSyncState({
        status: "success",
        message: `${result.indexed_count} docs, ${result.link_count} links`,
      });
      router.refresh();
    } catch (error) {
      setSyncState({
        status: "error",
        message: error instanceof Error ? error.message : "Reload failed",
      });
    }
  }

  return (
    <div className="project-sync-control">
      <button
        aria-label={`Sync documents for ${projectSlug}`}
        className="button project-sync-button"
        disabled={isDisabled}
        onClick={() => void reloadLinks()}
        title={disabled ? "Root path is required" : "Sync local markdown documents"}
        type="button"
      >
        <svg
          aria-hidden="true"
          fill="none"
          height="14"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
          viewBox="0 0 24 24"
          width="14"
        >
          <path d="M21 12a9 9 0 0 1-15.5 6.3" />
          <path d="M3 12a9 9 0 0 1 15.5-6.3" />
          <path d="M7 18H3v4" />
          <path d="M17 6h4V2" />
        </svg>
        <span>{isLoading ? "Syncing" : "Sync Documents"}</span>
      </button>
      {syncState.message ? (
        <span
          aria-live="polite"
          className={`project-sync-status ${syncState.status}`}
          title={syncState.message}
        >
          {syncState.message}
        </span>
      ) : null}
    </div>
  );
}
