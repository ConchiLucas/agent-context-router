"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  publishWorkspaceSharedFiles,
  restoreWorkspaceSharedFiles,
} from "@/lib/api";
import type { WorkspaceSharedFilesResult } from "@/lib/types";

interface WorkspaceRuntimeSyncProps {
  workspaceId: string;
}

type SharedFilesAction = "restore" | "publish";

const ACTION_COPY: Record<
  SharedFilesAction,
  { title: string; description: string; confirm: string; busy: string }
> = {
  restore: {
    title: "从数据库恢复到主目录",
    description: "原子恢复数据库中的文档、部署配置和运行脚本；失败时保留原目录。",
    confirm: "确认覆盖主目录",
    busy: "正在恢复…",
  },
  publish: {
    title: "用主目录覆盖数据库",
    description: "将主目录当前文档、部署配置和运行脚本保存为新的数据库版本。",
    confirm: "确认覆盖数据库",
    busy: "正在保存…",
  },
};

export function WorkspaceRuntimeSync({ workspaceId }: WorkspaceRuntimeSyncProps) {
  const [open, setOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState<SharedFilesAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<WorkspaceSharedFilesResult | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const close = useCallback(() => {
    if (busy) return;
    setOpen(false);
    setPendingAction(null);
    setError("");
    setResult(null);
  }, [busy]);

  useEffect(() => {
    if (!open) return;
    closeButtonRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) close();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, busy, close]);

  async function runAction() {
    if (!pendingAction || busy) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const next =
        pendingAction === "restore"
          ? await restoreWorkspaceSharedFiles(workspaceId)
          : await publishWorkspaceSharedFiles(workspaceId);
      setResult(next);
      setPendingAction(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "工作空间文件同步失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className="secondary-button"
        onClick={() => setOpen(true)}
      >
        工作空间文件
      </button>
      {open ? (
        <div className="project-settings-modal" role="presentation">
          <section
            className="management-modal workspace-runtime-sync-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="workspace-shared-files-title"
            data-workspace-detail-subdialog
            onKeyDown={(event) => {
              if (event.key !== "Escape") return;
              event.preventDefault();
              event.stopPropagation();
              close();
            }}
          >
            <header>
              <div>
                <span className="file-chip">主映射目录</span>
                <h2 id="workspace-shared-files-title">工作空间文件</h2>
              </div>
              <button
                ref={closeButtonRef}
                type="button"
                className="close-button"
                aria-label="关闭"
                onClick={close}
                disabled={busy}
              >
                ×
              </button>
            </header>

            <div className="workspace-shared-files-content">
              <p className="workspace-runtime-sync-note">
                数据库保存带摘要的版本；恢复会先暂存并校验，再原子替换主目录中的受管目录。
              </p>
              {error ? <div className="error-banner" role="alert">{error}</div> : null}
              {result ? (
                <div className="success-banner" role="status">
                  操作完成：版本 {result.revision}，文档 {result.document_count} 个，部署文件 {result.deploy_count} 个，脚本 {result.script_count + result.host_runtime_count} 个。
                </div>
              ) : null}
              <div className="workspace-shared-files-actions">
                {(Object.keys(ACTION_COPY) as SharedFilesAction[]).map((action) => (
                  <button
                    type="button"
                    key={action}
                    onClick={() => {
                      setPendingAction(action);
                      setError("");
                      setResult(null);
                    }}
                    disabled={busy}
                  >
                    <strong>{ACTION_COPY[action].title}</strong>
                    <span>{ACTION_COPY[action].description}</span>
                  </button>
                ))}
              </div>
              {pendingAction ? (
                <div className="workspace-shared-files-confirm" role="alert">
                  <strong>这个操作会删除原内容，且不能从界面撤销。</strong>
                  <p>{ACTION_COPY[pendingAction].description}</p>
                </div>
              ) : null}
            </div>

            <footer>
              <button type="button" className="secondary-button" onClick={close} disabled={busy}>
                关闭
              </button>
              {pendingAction ? (
                <button type="button" className="primary-button" onClick={() => void runAction()} disabled={busy}>
                  {busy ? ACTION_COPY[pendingAction].busy : ACTION_COPY[pendingAction].confirm}
                </button>
              ) : null}
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}
