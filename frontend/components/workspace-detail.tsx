"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { WorkspaceMcpEnvironmentDefaults } from "@/components/workspace-mcp-environment-defaults";
import {
  ProjectDashboard,
  type ProjectDashboardHandle,
} from "@/components/project-dashboard";
import { WorkspaceRuntimeSync } from "@/components/workspace-runtime-sync";
import type { ProjectKind, WorkspaceSummary } from "@/lib/types";

interface WorkspaceDetailProps {
  workspace: WorkspaceSummary;
  onBack: () => void;
}

type WorkspaceDetailTab = ProjectKind;

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter(
    (element) =>
      element.getAttribute("aria-hidden") !== "true" && element.offsetParent !== null,
  );
}

export function WorkspaceDetail({
  workspace,
  onBack,
}: WorkspaceDetailProps) {
  const [tab, setTab] = useState<WorkspaceDetailTab>("frontend");
  const currentWorkspace = workspace;
  const [projectCounts, setProjectCounts] = useState<Record<ProjectKind, number>>({
    frontend: 0,
    backend: 0,
  });
  const projectDashboardRef = useRef<ProjectDashboardHandle>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const detailRef = useRef<HTMLElement>(null);
  const environmentButtonRef = useRef<HTMLButtonElement>(null);
  const [showEnvironmentDetails, setShowEnvironmentDetails] = useState(false);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  const updateProjectCounts = useCallback(
    (counts: Record<ProjectKind, number>) => {
      setProjectCounts(counts);
    },
    [],
  );

  return (
    <section
      className="workspace-detail"
      role="dialog"
      aria-modal="true"
      aria-label={`${currentWorkspace.name} 工作空间详情`}
      onKeyDown={(event) => {
        if (
          event.target instanceof Element &&
          event.target.closest("[data-workspace-detail-subdialog]")
        ) {
          return;
        }
        if (event.key === "Escape") onBack();
        if (event.key !== "Tab") return;

        const focusable = detailRef.current
          ? focusableElements(detailRef.current)
          : [];
        if (focusable.length === 0) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }}
      ref={detailRef}
    >
      <header className="workspace-detail-header">
        <button
          type="button"
          className="close-button workspace-detail-close-button"
          aria-label="关闭工作空间详情"
          onClick={onBack}
          ref={closeButtonRef}
        >
          ×
        </button>
        <div className="workspace-detail-title">
          <div>
            <h1>{currentWorkspace.name}</h1>
            <code>{currentWorkspace.root_path}</code>
          </div>
        </div>
      </header>


      <div className="workspace-context-actions" aria-label="工作空间操作">
        <WorkspaceRuntimeSync workspaceId={currentWorkspace.id} />
        <button
          type="button"
          className="secondary-button"
          onClick={() => projectDashboardRef.current?.showMcpIntegration()}
        >
          MCP 接入
        </button>
        <button
          ref={environmentButtonRef}
          type="button"
          className="secondary-button workspace-environment-button"
          data-environment="local"
          onClick={() => setShowEnvironmentDetails(true)}
        >
          环境详情
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={() =>
            projectDashboardRef.current?.showWorkspaceTaskHistory()
          }
        >
          查看调用记录
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={() => projectDashboardRef.current?.showWorkspaceTree()}
        >
          查看文档树
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={() =>
            projectDashboardRef.current?.showWorkspaceMcpPreview()
          }
        >
          查看 MCP JSON
        </button>
      </div>

      <nav
        className="workspace-detail-tabs"
        role="tablist"
        aria-label="工作空间详情"
      >
        <button
          type="button"
          role="tab"
          aria-selected={tab === "frontend"}
          data-active={tab === "frontend"}
          onClick={() => setTab("frontend")}
        >
          <span>前端项目</span>
          <small>{projectCounts.frontend}</small>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "backend"}
          data-active={tab === "backend"}
          onClick={() => setTab("backend")}
        >
          <span>后端项目</span>
          <small>{projectCounts.backend}</small>
        </button>
      </nav>

      <ProjectDashboard
        ref={projectDashboardRef}
        workspace={currentWorkspace}
        projectKind={tab}
        visible
        onProjectCountsChanged={updateProjectCounts}
      />
      {showEnvironmentDetails ? (
        <WorkspaceMcpEnvironmentDefaults
          workspaceId={currentWorkspace.id}
          onClose={() => {
            setShowEnvironmentDetails(false);
            window.requestAnimationFrame(() => environmentButtonRef.current?.focus());
          }}
        />
      ) : null}
    </section>
  );
}
