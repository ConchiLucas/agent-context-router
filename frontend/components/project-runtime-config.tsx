"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  executeProjectRuntimeMode,
  getProjectRuntimeRun,
  getProjectRuntimeRunLog,
  getProjectRuntimeConfig,
  materializeProjectRuntimeMode,
  saveProjectRuntimeMode,
  type RuntimeConfigFile,
  type RuntimeMode,
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

function starterContent(path: string): string {
  if (path.endsWith(".sh")) return "#!/usr/bin/env sh\nset -eu\n\n";
  if (path.toLowerCase().includes("dockerfile")) return "# Runtime Runner build file\n\n";
  return "";
}

function fileKind(path: string): string {
  const lowerPath = path.toLowerCase();
  if (lowerPath.includes("dockerfile")) return "DOCKER";
  if (lowerPath.endsWith(".yml") || lowerPath.endsWith(".yaml")) return "YAML";
  if (lowerPath.endsWith(".sh")) return "SHELL";
  if (lowerPath.endsWith(".json")) return "JSON";
  return "FILE";
}

export function ProjectRuntimeConfigEditor({
  projectId,
}: ProjectRuntimeConfigProps) {
  const router = useRouter();
  const lineGutterRef = useRef<HTMLPreElement>(null);
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [mode, setMode] = useState<RuntimeMode>("fast");
  const [files, setFiles] = useState<Record<RuntimeMode, RuntimeConfigFile[]>>({
    fast: [],
    full: [],
  });
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [dirty, setDirty] = useState<Record<RuntimeMode, boolean>>({
    fast: false,
    full: false,
  });
  const [newPath, setNewPath] = useState("");
  const [creatingFile, setCreatingFile] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [materializing, setMaterializing] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [activeRun, setActiveRun] = useState<RuntimeRunSummary | null>(null);
  const [runLog, setRunLog] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    void getProjectRuntimeConfig(projectId)
      .then((config) => {
        if (!active) return;
        setProject(config.project);
        setFiles({
          fast: config.fast.files,
          full: config.full.files,
        });
        setSelectedPath(config.fast.files[0]?.relative_path ?? null);
        setError(null);
      })
      .catch((requestError: Error) => {
        if (active) setError(requestError.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  useEffect(() => {
    if (
      !activeRun ||
      ["succeeded", "failed", "cancelled"].includes(activeRun.status)
    ) {
      return;
    }
    let active = true;
    const runId = activeRun.id;
    const refreshRun = async () => {
      try {
        const [nextRun, nextLog] = await Promise.all([
          getProjectRuntimeRun(projectId, runId),
          getProjectRuntimeRunLog(projectId, runId),
        ]);
        if (!active) return;
        setActiveRun(nextRun);
        setRunLog(nextLog.content);
        if (["succeeded", "failed", "cancelled"].includes(nextRun.status)) {
          setNotice(
            nextRun.status === "succeeded"
              ? "更新任务执行成功"
              : nextRun.error_message ?? "更新任务执行失败",
          );
        }
      } catch (requestError) {
        if (active) setError((requestError as Error).message);
      }
    };
    void refreshRun();
    const timer = window.setInterval(() => void refreshRun(), 1200);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [activeRun?.id, activeRun?.status, projectId]);

  const activeFiles = files[mode];
  const activeFile =
    activeFiles.find((file) => file.relative_path === selectedPath) ?? null;
  const lineCount = Math.max(activeFile?.content.split("\n").length ?? 1, 1);

  function selectMode(nextMode: RuntimeMode) {
    setMode(nextMode);
    setSelectedPath(files[nextMode][0]?.relative_path ?? null);
    setCreatingFile(false);
    setNotice(null);
  }

  function updateActiveFile(patch: Partial<RuntimeConfigFile>) {
    if (!activeFile) return;
    setFiles((current) => ({
      ...current,
      [mode]: current[mode].map((file) =>
        file.relative_path === activeFile.relative_path
          ? { ...file, ...patch }
          : file,
      ),
    }));
    setDirty((current) => ({ ...current, [mode]: true }));
    setNotice(null);
  }

  function addFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const relativePath = newPath.trim().replace(/^\.\/+/, "");
    if (
      !relativePath ||
      relativePath.includes("..") ||
      relativePath.startsWith("/")
    ) {
      setError("请输入项目部署目录内的有效相对路径");
      return;
    }
    if (activeFiles.some((file) => file.relative_path === relativePath)) {
      setError("当前模式下已经存在这个文件");
      return;
    }
    const now = new Date().toISOString();
    const nextFile: RuntimeConfigFile = {
      id: `draft-${Date.now()}`,
      relative_path: relativePath,
      content: starterContent(relativePath),
      executable: relativePath.endsWith(".sh"),
      created_at: now,
      updated_at: now,
    };
    setFiles((current) => ({
      ...current,
      [mode]: [...current[mode], nextFile],
    }));
    setSelectedPath(relativePath);
    setDirty((current) => ({ ...current, [mode]: true }));
    setNewPath("");
    setCreatingFile(false);
    setError(null);
    setNotice(null);
  }

  function removeFile(file: RuntimeConfigFile) {
    if (!window.confirm(`从${MODE_COPY[mode].label}中删除 ${file.relative_path}？`)) {
      return;
    }
    const remaining = activeFiles.filter(
      (item) => item.relative_path !== file.relative_path,
    );
    setFiles((current) => ({ ...current, [mode]: remaining }));
    if (selectedPath === file.relative_path) {
      setSelectedPath(remaining[0]?.relative_path ?? null);
    }
    setDirty((current) => ({ ...current, [mode]: true }));
    setNotice(null);
  }

  async function saveCurrentMode() {
    setSaving(true);
    try {
      const saved = await saveProjectRuntimeMode(
        projectId,
        mode,
        activeFiles.map((file) => ({
          relative_path: file.relative_path,
          content: file.content,
          executable: file.executable,
        })),
      );
      setFiles((current) => ({ ...current, [mode]: saved.files }));
      setSelectedPath((current) =>
        saved.files.some((file) => file.relative_path === current)
          ? current
          : saved.files[0]?.relative_path ?? null,
      );
      setDirty((current) => ({ ...current, [mode]: false }));
      setError(null);
      setNotice(`${MODE_COPY[mode].label}配置已保存`);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function materializeCurrentMode() {
    setMaterializing(true);
    try {
      const result = await materializeProjectRuntimeMode(projectId, mode);
      setError(null);
      setNotice(`已生成 ${result.file_count} 个文件：${result.materialized_path}`);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setMaterializing(false);
    }
  }

  async function executeCurrentMode() {
    setExecuting(true);
    try {
      const run = await executeProjectRuntimeMode(projectId, mode);
      setActiveRun(run);
      setRunLog("");
      setError(null);
      setNotice(`任务 ${run.id.slice(0, 8)} 已进入队列`);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setExecuting(false);
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
            <span>Runtime Runner</span>
            <h1>{project?.name ?? "运行配置"}</h1>
            <p>
              {project
                ? `${project.project_kind === "frontend" ? "前端项目" : "后端项目"} · ${project.relative_path}`
                : "正在读取项目配置…"}
            </p>
          </div>
        </div>
        <div className="runtime-config-header-actions">
          {notice ? <span className="runtime-save-notice">{notice}</span> : null}
          <button
            type="button"
            className="runtime-materialize-button"
            disabled={
              loading ||
              saving ||
              materializing ||
              dirty[mode] ||
              activeFiles.length === 0
            }
            onClick={() => void materializeCurrentMode()}
          >
            {materializing ? "生成中…" : "生成文件"}
          </button>
          <button
            type="button"
            className="runtime-save-button"
            disabled={loading || saving || !dirty[mode]}
            onClick={() => void saveCurrentMode()}
          >
            {saving ? "保存中…" : "保存配置"}
          </button>
          <button
            type="button"
            className="runtime-execute-button"
            title={
              activeFiles.some((file) => file.relative_path === "deploy.sh")
                ? "执行当前更新配置"
                : "请先添加并保存 deploy.sh"
            }
            disabled={
              loading ||
              saving ||
              materializing ||
              executing ||
              dirty[mode] ||
              !activeFiles.some((file) => file.relative_path === "deploy.sh")
            }
            onClick={() => void executeCurrentMode()}
          >
            {executing ? "启动中…" : "执行更新"}
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
                {dirty[item] ? <i aria-label="有未保存修改" /> : null}
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
            <button
              type="button"
              onClick={() => setCreatingFile((current) => !current)}
            >
              ＋ 新建
            </button>
          </div>

          {creatingFile ? (
            <form className="runtime-new-file-form" onSubmit={addFile}>
              <input
                autoFocus
                value={newPath}
                onChange={(event) => setNewPath(event.target.value)}
                placeholder="例如 Dockerfile.fast"
              />
              <div>
                <button type="submit">添加</button>
                <button type="button" onClick={() => setCreatingFile(false)}>
                  取消
                </button>
              </div>
            </form>
          ) : null}

          <div className="runtime-file-list">
            {loading ? <p>正在读取文件…</p> : null}
            {!loading && activeFiles.length === 0 ? (
              <div className="runtime-file-empty">
                <span>＋</span>
                <strong>还没有部署文件</strong>
                <p>新建 Dockerfile、Compose 或 Shell 脚本开始配置。</p>
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
                <button
                  type="button"
                  className="runtime-file-delete"
                  aria-label={`删除 ${file.relative_path}`}
                  onClick={() => removeFile(file)}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </aside>

        <section className="runtime-editor-panel">
          {activeFile ? (
            <>
              <header className="runtime-editor-toolbar">
                <div>
                  <span>{fileKind(activeFile.relative_path)}</span>
                  <strong>{activeFile.relative_path}</strong>
                  {dirty[mode] ? <small>未保存</small> : null}
                </div>
                <label>
                  <input
                    type="checkbox"
                    checked={activeFile.executable}
                    onChange={(event) =>
                      updateActiveFile({ executable: event.target.checked })
                    }
                  />
                  可执行文件
                </label>
              </header>
              <div className="runtime-code-editor">
                <pre ref={lineGutterRef} aria-hidden="true">
                  {Array.from({ length: lineCount }, (_, index) => (
                    <span key={index}>{index + 1}</span>
                  ))}
                </pre>
                <textarea
                  aria-label={`${activeFile.relative_path} 文件内容`}
                  spellCheck={false}
                  wrap="off"
                  value={activeFile.content}
                  onChange={(event) =>
                    updateActiveFile({ content: event.target.value })
                  }
                  onScroll={(event) => {
                    if (lineGutterRef.current) {
                      lineGutterRef.current.scrollTop =
                        event.currentTarget.scrollTop;
                    }
                  }}
                />
              </div>
              <footer className="runtime-editor-status">
                <span>{lineCount} 行</span>
                <span>UTF-8</span>
                <span>{activeFile.executable ? "Executable" : "Regular file"}</span>
              </footer>
            </>
          ) : (
            <div className="runtime-editor-empty">
              <span>{"{ }"}</span>
              <h2>选择或新建部署文件</h2>
              <p>文件内容保存在数据库中，执行时再由 Runtime Runner 映射到磁盘。</p>
            </div>
          )}
        </section>
      </div>
      {activeRun ? (
        <section className="runtime-run-console">
          <header>
            <div>
              <span data-status={activeRun.status}>
                {activeRun.status === "queued"
                  ? "排队中"
                  : activeRun.status === "running"
                    ? "执行中"
                    : activeRun.status === "succeeded"
                      ? "已成功"
                      : activeRun.status === "cancelled"
                        ? "已取消"
                        : "失败"}
              </span>
              <strong>任务 {activeRun.id.slice(0, 8)}</strong>
              <small>{activeRun.mode === "fast" ? "快速更新" : "完整更新"}</small>
            </div>
            <button type="button" onClick={() => setActiveRun(null)}>
              ×
            </button>
          </header>
          <pre>{runLog || "等待 Runtime Runner 输出…"}</pre>
        </section>
      ) : null}
    </main>
  );
}
