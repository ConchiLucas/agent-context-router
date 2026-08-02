"use client";

import { useState } from "react";

import {
  commitWorkspaceDeploySync,
  previewWorkspaceDeploySync,
  type WorkspaceDeployChangeSummary,
  type WorkspaceDeploySyncPreview,
} from "@/lib/runtime-api";

interface WorkspaceRuntimeSyncProps {
  workspaceId: string;
}

export function workspaceDeployChangeLabel(
  changes: WorkspaceDeployChangeSummary,
): string {
  return `新增 ${changes.additions} · 更新 ${changes.updates} · 删除 ${changes.deletions}`;
}

export function canCommitWorkspaceDeploySync(
  preview: WorkspaceDeploySyncPreview | null,
  busy: boolean,
): boolean {
  return Boolean(preview?.valid && !busy);
}

export function WorkspaceRuntimeSync({
  workspaceId,
}: WorkspaceRuntimeSyncProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [preview, setPreview] = useState<WorkspaceDeploySyncPreview | null>(null);
  const [error, setError] = useState("");

  async function loadPreview() {
    setOpen(true);
    setLoading(true);
    setPreview(null);
    setError("");
    try {
      setPreview(await previewWorkspaceDeploySync(workspaceId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "deploy 配置预览失败");
    } finally {
      setLoading(false);
    }
  }

  async function commit() {
    if (!preview || !canCommitWorkspaceDeploySync(preview, committing)) return;
    setCommitting(true);
    setError("");
    try {
      setPreview(await commitWorkspaceDeploySync(workspaceId, preview.digest));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "deploy 配置同步失败");
    } finally {
      setCommitting(false);
    }
  }

  function close() {
    if (loading || committing) return;
    setOpen(false);
    setPreview(null);
    setError("");
  }

  return (
    <>
      <button type="button" className="secondary-button" onClick={loadPreview}>
        同步 deploy 配置
      </button>
      {open ? (
        <div className="project-settings-modal" role="presentation">
          <section
            className="management-modal workspace-runtime-sync-modal"
            role="dialog"
            aria-modal="true"
            aria-label="同步 deploy 配置"
          >
            <header>
              <div>
                <span className="file-chip">Repository source of truth</span>
                <h2>同步 deploy 配置</h2>
              </div>
              <button
                type="button"
                className="close-button"
                aria-label="关闭同步窗口"
                onClick={close}
                disabled={loading || committing}
              >
                ×
              </button>
            </header>

            {loading ? <p className="empty-message">正在扫描并校验固定目录…</p> : null}
            {error ? <div className="error-banner">{error}</div> : null}
            {preview ? (
              <div className="workspace-runtime-sync-content">
                <div className="workspace-runtime-sync-source">
                  <span>扫描来源</span>
                  <code>{preview.source_root}</code>
                </div>
                <div className="workspace-runtime-sync-total">
                  <strong>{workspaceDeployChangeLabel(preview.total)}</strong>
                  <small>摘要 {preview.digest.slice(0, 12)}</small>
                </div>
                <div className="workspace-runtime-sync-profiles">
                  {preview.profiles.map((profile) => (
                    <article key={`${profile.owner}-${profile.mode}`}>
                      <div>
                        <strong>{profile.owner}</strong>
                        <span>{profile.mode}</span>
                      </div>
                      <div>
                        <span>{profile.file_count} 个文件</span>
                        <small>{workspaceDeployChangeLabel(profile.changes)}</small>
                      </div>
                    </article>
                  ))}
                </div>
                {preview.synchronized ? (
                  <div className="success-banner" role="status">
                    已按当前摘要原子同步，数据库运行配置已更新。
                  </div>
                ) : (
                  <p className="workspace-runtime-sync-note">
                    确认后会在一个事务中替换 Workspace start、policy 和所有 Project
                    的 fast/full 配置。任何失败都会保留原配置。
                  </p>
                )}
              </div>
            ) : null}

            <footer>
              <button
                type="button"
                className="secondary-button"
                onClick={close}
                disabled={loading || committing}
              >
                {preview?.synchronized ? "关闭" : "取消"}
              </button>
              {!preview?.synchronized ? (
                <button
                  type="button"
                  className="primary-button"
                  onClick={commit}
                  disabled={!canCommitWorkspaceDeploySync(preview, committing || loading)}
                >
                  {committing ? "正在同步…" : "确认同步"}
                </button>
              ) : null}
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}
