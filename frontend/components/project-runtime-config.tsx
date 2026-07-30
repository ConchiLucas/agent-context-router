"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  getProjectRuntimeConfig,
  getProjectRuntimeRun,
  getProjectRuntimeRunLog,
  listProjectRuntimeRuns,
  type RuntimeConfigFile,
  type RuntimeMode,
  type RuntimeRunStatus,
  type RuntimeRunSummary,
} from "@/lib/runtime-api";
import type { ProjectSummary } from "@/lib/types";

interface ProjectRuntimeConfigProps {
  projectId: string;
}

const MODE_COPY: Record<
  RuntimeMode,
  { label: string; eyebrow: string; description: string }
> = {
  fast: {
    label: "快速更新",
    eyebrow: "增量",
    description: "依赖未变化时复用缓存，只更新业务代码。",
  },
  full: {
    label: "完整更新",
    eyebrow: "全量",
    description: "依赖、基础镜像或构建环境变化时完整重建。",
  },
};

const ACTIVE_RUN_STATUSES = new Set<RuntimeRunStatus>(["queued", "running"]);

function fileKind(path: string): string {
  const lowerPath = path.toLowerCase();
  if (lowerPath.includes("dockerfile")) return "DOCKER";
  if (lowerPath.endsWith(".yml") || lowerPath.endsWith(".yaml")) return "YAML";
  if (lowerPath.endsWith(".sh")) return "SHELL";
  if (lowerPath.endsWith(".json")) return "JSON";
  return "FILE";
}

function runStatusLabel(status: RuntimeRunStatus): string {
  if (status === "queued") return "排队中";
  if (status === "running") return "执行中";
  if (status === "succeeded") return "已成功";
  if (status === "cancelled") return "已取消";
  return "失败";
}

function formattedTime(value: string | null): string {
  if (!value) return "尚未开始";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value));
}

export function ProjectRuntimeConfigEditor({
  projectId,
}: ProjectRuntimeConfigProps) {
  const router = useRouter();
  const lineGutterRef = useRef<HTMLPreElement>(null);
  const modeRef = useRef<RuntimeMode>("fast");
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [mode, setMode] = useState<RuntimeMode>("fast");
  const [files, setFiles] = useState<Record<RuntimeMode, RuntimeConfigFile[]>>({
    fast: [],
    full: [],
  });
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [runs, setRuns] = useState<RuntimeRunSummary[]>([]);
  const [activeRun, setActiveRun] = useState<RuntimeRunSummary | null>(null);
  const [runLog, setRunLog] = useState("");
  const [loading, setLoading] = useState(true);
  const [runLoading, setRunLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPage = useCallback(async () => {
    setLoading(true);
    try {
      const [config, nextRuns] = await Promise.all([
        getProjectRuntimeConfig(projectId),
        listProjectRuntimeRuns(projectId),
      ]);
      setProject(config.project);
      setFiles({
        fast: config.fast.files,
        full: config.full.files,
      });
      setRuns(nextRuns);
      const currentFiles = config[modeRef.current].files;
      setSelectedPath((current) =>
        currentFiles.some((file) => file.relative_path === current)
          ? current
          : currentFiles[0]?.relative_path ?? null,
      );
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadPage();
  }, [loadPage]);

  useEffect(() => {
    if (
      !runs.some((run) => ACTIVE_RUN_STATUSES.has(run.status)) &&
      (!activeRun || !ACTIVE_RUN_STATUSES.has(activeRun.status))
    ) {
      return;
    }
    let active = true;
    const refreshRuns = async () => {
      try {
        const nextRuns = await listProjectRuntimeRuns(projectId);
        if (!active) return;
        setRuns(nextRuns);
        if (activeRun) {
          const nextRun = nextRuns.find((run) => run.id === activeRun.id);
          if (nextRun) setActiveRun(nextRun);
          const nextLog = await getProjectRuntimeRunLog(
            projectId,
            activeRun.id,
          );
          if (active) setRunLog(nextLog.content);
        }
      } catch (requestError) {
        if (active) setError((requestError as Error).message);
      }
    };
    const timer = window.setInterval(() => void refreshRuns(), 1500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [activeRun, projectId, runs]);

  const activeFiles = files[mode];
  const activeFile =
    activeFiles.find((file) => file.relative_path === selectedPath) ?? null;
  const lineCount = Math.max(activeFile?.content.split("\n").length ?? 1, 1);

  function selectMode(nextMode: RuntimeMode) {
    modeRef.current = nextMode;
    setMode(nextMode);
    setSelectedPath(files[nextMode][0]?.relative_path ?? null);
  }

  async function openRun(run: RuntimeRunSummary) {
    setRunLoading(true);
    setActiveRun(run);
    setRunLog("");
    try {
      const [nextRun, nextLog] = await Promise.all([
        getProjectRuntimeRun(projectId, run.id),
        getProjectRuntimeRunLog(projectId, run.id),
      ]);
      setActiveRun(nextRun);
      setRunLog(nextLog.content);
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setRunLoading(false);
    }
  }

  return (
    <main className="runtime-config-page">
      <header className="runtime-config-header">
        <div className="runtime-config-heading">
          <button
            type="button"
            className="runtime-back-button"
            onClick={() => router.back()}
          >
            <span aria-hidden="true">←</span>
            返回
          </button>
          <div className="runtime-config-title-mark" aria-hidden="true">
            {"</>"}
          </div>
          <div>
            <span>Runtime Runner · 只读</span>
            <h1>{project?.name ?? "运行配置"}</h1>
            <p>
              {project
                ? `${project.project_kind === "frontend" ? "前端项目" : "后端项目"} · ${project.relative_path}`
                : "正在读取项目配置…"}
            </p>
          </div>
        </div>
        <div className="runtime-config-header-actions">
          <span className="runtime-save-notice">
            配置和执行由 AI / Runtime Runner 维护
          </span>
          <button
            type="button"
            className="runtime-materialize-button"
            disabled={loading}
            onClick={() => void loadPage()}
          >
            {loading ? "正在加载…" : "重新加载"}
          </button>
        </div>
      </header>

      {error ? (
        <div className="runtime-error-banner" role="alert">
          {error}
          <button type="button" onClick={() => setError(null)}>
            ×
          </button>
        </div>
      ) : null}

      <div className="runtime-config-workbench">
        <aside className="runtime-file-sidebar">
          <div className="runtime-mode-tabs" role="tablist" aria-label="更新方式">
            {(Object.keys(MODE_COPY) as RuntimeMode[]).map((item) => (
              <button
                type="button"
                role="tab"
                aria-selected={mode === item}
                data-active={mode === item}
                key={item}
                onClick={() => selectMode(item)}
              >
                <small>{MODE_COPY[item].eyebrow}</small>
                <strong>{MODE_COPY[item].label}</strong>
              </button>
            ))}
          </div>

          <div className="runtime-mode-summary">
            <span>{MODE_COPY[mode].eyebrow} DEPLOYMENT</span>
            <p>{MODE_COPY[mode].description}</p>
          </div>

          <div className="runtime-file-list-header">
            <div>
              <strong>部署文件</strong>
              <span>{activeFiles.length}</span>
            </div>
          </div>

          <div className="runtime-file-list">
            {loading ? <p>正在读取文件…</p> : null}
            {!loading && activeFiles.length === 0 ? (
              <div className="runtime-file-empty">
                <span>{"{ }"}</span>
                <strong>当前模式没有部署文件</strong>
                <p>可让 AI 为这个项目维护运行配置。</p>
              </div>
            ) : null}
            {activeFiles.map((file) => (
              <div
                className="runtime-file-row"
                data-active={selectedPath === file.relative_path}
                key={file.id}
              >
                <button
                  type="button"
                  className="runtime-file-select"
                  onClick={() => setSelectedPath(file.relative_path)}
                >
                  <span>{fileKind(file.relative_path)}</span>
                  <strong>{file.relative_path}</strong>
                </button>
              </div>
            ))}
          </div>

          <section className="runtime-run-history" aria-label="最近运行记录">
            <header>
              <strong>最近运行</strong>
              <span>{runs.length}</span>
            </header>
            <div>
              {runs.length === 0 ? (
                <p>暂无运行记录</p>
              ) : (
                runs.map((run) => (
                  <button
                    type="button"
                    data-status={run.status}
                    key={run.id}
                    onClick={() => void openRun(run)}
                  >
                    <span>{runStatusLabel(run.status)}</span>
                    <strong>{run.id.slice(0, 8)}</strong>
                    <small>{formattedTime(run.created_at)}</small>
                  </button>
                ))
              )}
            </div>
          </section>
        </aside>

        <section className="runtime-editor-panel">
          {activeFile ? (
            <>
              <header className="runtime-editor-toolbar">
                <div>
                  <span>{fileKind(activeFile.relative_path)}</span>
                  <strong>{activeFile.relative_path}</strong>
                </div>
                <label>
                  {activeFile.executable ? "可执行文件" : "普通文件"}
                </label>
              </header>
              <div className="runtime-code-editor">
                <pre ref={lineGutterRef} aria-hidden="true">
                  {Array.from({ length: lineCount }, (_, index) => (
                    <span key={index}>{index + 1}</span>
                  ))}
                </pre>
                <textarea
                  aria-label={`${activeFile.relative_path} 文件内容（只读）`}
                  readOnly
                  spellCheck={false}
                  wrap="off"
                  value={activeFile.content}
                  onScroll={(event) => {
                    if (lineGutterRef.current) {
                      lineGutterRef.current.scrollTop =
                        event.currentTarget.scrollTop;
                    }
                  }}
                />
              </div>
              <footer className="runtime-editor-status">
                <span>只读</span>
                <span>{lineCount} 行</span>
                <span>UTF-8</span>
                <span>
                  {activeFile.executable ? "Executable" : "Regular file"}
                </span>
              </footer>
            </>
          ) : (
            <div className="runtime-editor-empty">
              <span>{"{ }"}</span>
              <h2>选择一个部署文件</h2>
              <p>这里仅展示数据库中已经保存的 Runtime Runner 配置。</p>
            </div>
          )}
        </section>
      </div>

      {activeRun ? (
        <section className="runtime-run-console">
          <header>
            <div>
              <span data-status={activeRun.status}>
                {runStatusLabel(activeRun.status)}
              </span>
              <strong>任务 {activeRun.id.slice(0, 8)}</strong>
              <small>
                {activeRun.mode === "fast" ? "快速更新" : "完整更新"} ·{" "}
                {activeRun.trigger === "mcp" ? "AI 触发" : "历史 UI 触发"}
              </small>
            </div>
            <button type="button" onClick={() => setActiveRun(null)}>
              ×
            </button>
          </header>
          <pre>
            {runLoading
              ? "正在读取运行日志…"
              : runLog || activeRun.error_message || "这次运行没有保存日志。"}
          </pre>
        </section>
      ) : null}
    </main>
  );
}
