"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { listManagedScripts, setManagedScriptAutostart } from "@/lib/api";
import type { ManagedScript, ManagedScriptList } from "@/lib/types";

export function ManagedScriptsManager() {
  const [listing, setListing] = useState<ManagedScriptList | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await listManagedScripts();
      setListing(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取脚本管理配置失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const projectStartScripts = useMemo(
    () => listing?.scripts.filter((item) => item.kind === "autostart") ?? [],
    [listing],
  );
  const globalScripts = useMemo(
    () => listing?.scripts.filter((item) => item.kind === "global") ?? [],
    [listing],
  );

  async function toggleAutostart(script: ManagedScript, enabled: boolean) {
    setBusyId(script.id);
    setError("");
    setNotice("");
    try {
      const next = await setManagedScriptAutostart(script.id, enabled);
      setListing((current) =>
        current
          ? {
              ...current,
              scripts: current.scripts.map((item) =>
                item.id === next.id ? next : item,
              ),
            }
          : current,
      );
      setNotice(
        enabled
          ? `已打开「${next.name}」跟随 Context Router 启动`
          : `已关闭「${next.name}」跟随 Context Router 启动`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "更新项目启动开关失败");
    } finally {
      setBusyId("");
    }
  }

  return (
    <section className="shared-ai-page managed-scripts-page" aria-label="脚本管理">
      <div className="shared-ai-content">
        {error ? (
          <p className="error-banner" role="alert">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p className="success-banner" role="status">
            {notice}
          </p>
        ) : null}
        {loading ? <p className="empty-message">正在读取脚本管理配置…</p> : null}
        {!loading && listing ? (
          <>
            <section className="managed-scripts-group">
              <div className="shared-ai-toolbar">
                <strong>Context Router 启动</strong>
                <span>{projectStartScripts.length} 个</span>
              </div>
              {projectStartScripts.length === 0 ? (
                <p className="empty-message">还没有可跟随 Context Router 启动的脚本。</p>
              ) : (
                <div className="managed-scripts-list">
                  {projectStartScripts.map((script) => (
                    <article key={script.id} className="managed-script-card">
                      <div className="managed-script-card-head">
                        <div>
                          <h2>{script.name}</h2>
                          <p>{script.description}</p>
                        </div>
                        <label className="managed-script-switch">
                          <input
                            type="checkbox"
                            checked={script.autostart_enabled}
                            disabled={!script.available || busyId === script.id}
                            onChange={(event) =>
                              void toggleAutostart(script, event.target.checked)
                            }
                          />
                          <span>
                            {script.autostart_enabled
                              ? "跟随 Context Router 启动"
                              : "不跟随 Context Router 启动"}
                          </span>
                        </label>
                      </div>
                      <dl className="managed-script-meta">
                        {script.workspace_name ? (
                          <>
                            <dt>工作空间</dt>
                            <dd>{script.workspace_name}</dd>
                          </>
                        ) : null}
                        {script.command_path ? (
                          <>
                            <dt>命令</dt>
                            <dd>
                              <code>{script.command_path}</code>
                            </dd>
                          </>
                        ) : null}
                        <dt>项目绑定</dt>
                        <dd>{script.autostart_installed ? "已绑定" : "未绑定"}</dd>
                      </dl>
                      {script.unavailable_reason ? (
                        <p className="managed-script-warning">{script.unavailable_reason}</p>
                      ) : null}
                    </article>
                  ))}
                </div>
              )}
            </section>
            <section className="managed-scripts-group">
              <div className="shared-ai-toolbar">
                <strong>全局脚本</strong>
                <span>{globalScripts.length} 个</span>
              </div>
              {globalScripts.length === 0 ? (
                <p className="empty-message">还没有全局脚本。</p>
              ) : (
                <div className="managed-scripts-list">
                  {globalScripts.map((script) => (
                    <article key={script.id} className="managed-script-card">
                      <div className="managed-script-card-head">
                        <div>
                          <h2>{script.name}</h2>
                          <p>{script.description}</p>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
          </>
        ) : null}
      </div>
    </section>
  );
}
