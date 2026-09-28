"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getWorkspaceScript, listWorkspaceScripts } from "@/lib/api";
import type { WorkspaceScriptDetail, WorkspaceScriptList } from "@/lib/types";

interface WorkspaceScriptsViewProps {
  workspaceId: string;
  workspaceName: string;
  scriptCount?: number;
}

export function WorkspaceScriptsView({
  workspaceId,
  workspaceName,
  scriptCount = 0,
}: WorkspaceScriptsViewProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [listing, setListing] = useState<WorkspaceScriptList | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [detail, setDetail] = useState<WorkspaceScriptDetail | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const close = useCallback(() => {
    if (busy) return;
    setOpen(false);
    setError("");
    setListing(null);
    setSelectedPath(null);
    setDetail(null);
  }, [busy]);

  const loadScripts = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const next = await listWorkspaceScripts(workspaceId);
      setListing(next);
      setSelectedPath((current) => {
        if (current && next.scripts.some((item) => item.relative_path === current)) {
          return current;
        }
        return next.scripts[0]?.relative_path ?? null;
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取数据库脚本失败");
    } finally {
      setBusy(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    void loadScripts();
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [loadScripts, open]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) close();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, close, open]);

  useEffect(() => {
    if (!open || !selectedPath) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setBusy(true);
    void getWorkspaceScript(workspaceId, selectedPath)
      .then((next) => {
        if (!cancelled) setDetail(next);
      })
      .catch((caught) => {
        if (!cancelled) {
          setDetail(null);
          setError(caught instanceof Error ? caught.message : "读取脚本正文失败");
        }
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, selectedPath, workspaceId]);

  return (
    <>
      <button
        type="button"
        className="secondary-button"
        onClick={() => setOpen(true)}
      >
        脚本{scriptCount > 0 ? ` ${scriptCount}` : ""}
      </button>
      {open ? (
        <section
          className="workspace-scripts-fullscreen"
          role="dialog"
          aria-modal="true"
          aria-label={`${workspaceName} 脚本`}
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.preventDefault();
            event.stopPropagation();
            close();
          }}
        >
          <button
            ref={closeButtonRef}
            type="button"
            className="close-button workspace-detail-close-button"
            aria-label="关闭脚本"
            onClick={close}
            disabled={busy}
          >
            ×
          </button>

          <div className="workspace-scripts-content">
            {error ? <div className="error-banner" role="alert">{error}</div> : null}
            {listing && listing.scripts.length === 0 ? (
              <p className="empty-message">数据库当前版本没有脚本。</p>
            ) : null}
            {listing && listing.scripts.length > 0 ? (
              <div className="workspace-scripts-panes">
                <div className="workspace-scripts-table-wrap">
                  <table className="workspace-scripts-table">
                    <thead>
                      <tr>
                        <th scope="col">脚本</th>
                        <th scope="col">作用</th>
                      </tr>
                    </thead>
                    <tbody>
                      {listing.scripts.map((script) => (
                        <tr
                          key={script.relative_path}
                          data-active={script.relative_path === selectedPath}
                        >
                          <th scope="row">
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedPath(script.relative_path);
                                setError("");
                              }}
                            >
                              <strong>{script.name}</strong>
                              <span>{script.relative_path}</span>
                            </button>
                          </th>
                          <td>{script.description || "暂无说明"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <pre className="workspace-scripts-body" tabIndex={0}>
                  {detail?.relative_path === selectedPath
                    ? detail.content
                    : busy
                      ? "正在读取…"
                      : "选择左侧脚本查看正文"}
                </pre>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
    </>
  );
}
