"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { WorkspaceDetail } from "@/components/workspace-detail";
import {
  createWorkspace,
  deleteWorkspace,
  listWorkspaces,
  setWorkspaceEnabled,
  updateWorkspace,
} from "@/lib/api";
import type { WorkspaceSummary } from "@/lib/types";

const ALL_WORKSPACE_TYPES = "__all__";
const DEFAULT_WORKSPACE_TYPE = "公司项目";

interface WorkspaceFormState {
  name: string;
  workspaceType: string;
  rootPath: string;
  enabled: boolean;
}

const EMPTY_FORM: WorkspaceFormState = {
  name: "",
  workspaceType: DEFAULT_WORKSPACE_TYPE,
  rootPath: "",
  enabled: true,
};

function workspaceForm(workspace?: WorkspaceSummary): WorkspaceFormState {
  if (!workspace) return { ...EMPTY_FORM };
  return {
    name: workspace.name,
    workspaceType: workspace.workspace_type,
    rootPath: workspace.root_path,
    enabled: workspace.enabled,
  };
}

function formattedTime(value?: string | null): string {
  if (!value) return "尚未更新";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function WorkspaceDashboard() {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [activeWorkspace, setActiveWorkspace] =
    useState<WorkspaceSummary | null>(null);
  const [selectedType, setSelectedType] = useState(ALL_WORKSPACE_TYPES);
  const [editor, setEditor] = useState<WorkspaceSummary | "new" | null>(null);
  const [form, setForm] = useState<WorkspaceFormState>({ ...EMPTY_FORM });
  const [deletingWorkspace, setDeletingWorkspace] =
    useState<WorkspaceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyWorkspaceId, setBusyWorkspaceId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadWorkspaces = useCallback(async () => {
    setLoading(true);
    try {
      const next = await listWorkspaces();
      setWorkspaces(next);
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadWorkspaces();
  }, [loadWorkspaces]);

  useEffect(() => {
    if (
      selectedType !== ALL_WORKSPACE_TYPES &&
      !workspaces.some(
        (workspace) => workspace.workspace_type === selectedType,
      )
    ) {
      setSelectedType(ALL_WORKSPACE_TYPES);
    }
  }, [selectedType, workspaces]);

  function openEditor(workspace?: WorkspaceSummary) {
    setForm(workspaceForm(workspace));
    setEditor(workspace ?? "new");
    setError(null);
  }

  async function submitWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editor) return;
    const editorId = editor === "new" ? "new" : editor.id;
    setBusyWorkspaceId(editorId);
    try {
      const saved =
        editor === "new"
          ? await createWorkspace({
              name: form.name.trim(),
              workspace_type: form.workspaceType.trim(),
              root_path: form.rootPath.trim(),
              enabled: form.enabled,
            })
          : await updateWorkspace(editor.id, {
              name: form.name.trim(),
              workspace_type: form.workspaceType.trim(),
              root_path: form.rootPath.trim(),
            });
      const finalSaved =
        editor !== "new" && saved.enabled !== form.enabled
          ? await setWorkspaceEnabled(saved.id, form.enabled)
          : saved;
      setWorkspaces((current) =>
        editor === "new"
          ? [...current, finalSaved]
          : current.map((workspace) =>
              workspace.id === finalSaved.id ? finalSaved : workspace,
            ),
      );
      setSelectedType(finalSaved.workspace_type);
      setEditor(null);
      setForm({ ...EMPTY_FORM });
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusyWorkspaceId(null);
    }
  }

  async function toggleWorkspace(workspace: WorkspaceSummary) {
    setBusyWorkspaceId(workspace.id);
    try {
      const updated = await setWorkspaceEnabled(
        workspace.id,
        !workspace.enabled,
      );
      setWorkspaces((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusyWorkspaceId(null);
    }
  }

  async function confirmDeletion() {
    if (!deletingWorkspace) return;
    setBusyWorkspaceId(deletingWorkspace.id);
    try {
      await deleteWorkspace(deletingWorkspace.id);
      setWorkspaces((current) =>
        current.filter(
          (workspace) => workspace.id !== deletingWorkspace.id,
        ),
      );
      setDeletingWorkspace(null);
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusyWorkspaceId(null);
    }
  }

  if (activeWorkspace) {
    return (
      <WorkspaceDetail
        key={activeWorkspace.id}
        workspace={activeWorkspace}
        onBack={() => {
          setActiveWorkspace(null);
          void loadWorkspaces();
        }}
      />
    );
  }

  const workspaceTypes = Array.from(
    new Set(workspaces.map((workspace) => workspace.workspace_type)),
  ).sort((left, right) => left.localeCompare(right, "zh-CN"));
  const visibleWorkspaces =
    selectedType === ALL_WORKSPACE_TYPES
      ? workspaces
      : workspaces.filter(
          (workspace) => workspace.workspace_type === selectedType,
        );

  return (
    <>
      <nav
        className="project-type-tabs"
        role="tablist"
        aria-label="工作空间类型"
      >
        <button
          type="button"
          role="tab"
          aria-selected={selectedType === ALL_WORKSPACE_TYPES}
          data-active={selectedType === ALL_WORKSPACE_TYPES}
          onClick={() => setSelectedType(ALL_WORKSPACE_TYPES)}
        >
          <span>全部工作空间</span>
          <small>{workspaces.length}</small>
        </button>
        {workspaceTypes.map((type) => (
          <button
            type="button"
            role="tab"
            aria-selected={selectedType === type}
            data-active={selectedType === type}
            key={type}
            onClick={() => setSelectedType(type)}
          >
            <span>{type}</span>
            <small>
              {
                workspaces.filter(
                  (workspace) => workspace.workspace_type === type,
                ).length
              }
            </small>
          </button>
        ))}
      </nav>

      <div className="page-actions">
        <button
          type="button"
          className="primary-button"
          onClick={() => openEditor()}
        >
          添加工作空间
        </button>
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      {loading ? <p className="empty-message">正在读取工作空间…</p> : null}
      {!loading && workspaces.length === 0 ? (
        <div className="empty-state workspace-empty-state">
          <span className="workspace-empty-icon">◇</span>
          <h2>还没有工作空间</h2>
          <p>
            添加一个本机目录作为工作空间，再在其中配置根项目或嵌套子项目。
          </p>
          <button
            type="button"
            className="primary-button"
            onClick={() => openEditor()}
          >
            添加第一个工作空间
          </button>
        </div>
      ) : null}
      {!loading &&
      workspaces.length > 0 &&
      visibleWorkspaces.length === 0 ? (
        <div className="empty-state workspace-empty-state">
          <h2>这个类型还没有工作空间</h2>
          <p>可以添加工作空间，或编辑已有工作空间的类型。</p>
        </div>
      ) : null}

      <section className="workspace-grid" aria-label="工作空间列表">
        {visibleWorkspaces.map((workspace) => (
          <article
            className="workspace-card"
            data-enabled={workspace.enabled}
            key={workspace.id}
          >
            <header>
              <div>
                <div className="project-card-chips">
                  <span className="file-chip">Workspace</span>
                  <span className="project-type-chip">
                    {workspace.workspace_type}
                  </span>
                </div>
                <h2>{workspace.name}</h2>
              </div>
              <span
                className="project-status-chip"
                data-enabled={workspace.enabled}
              >
                {workspace.enabled ? "已启用" : "已停用"}
              </span>
            </header>
            <code className="workspace-root-path">{workspace.root_path}</code>
            <div className="workspace-card-stats">
              <div>
                <strong>{workspace.project_count ?? 0}</strong>
                <span>项目</span>
              </div>
              <div>
                <strong>{workspace.data_source_count ?? 0}</strong>
                <span>数据源</span>
              </div>
              <div>
                <strong>{workspace.database_count ?? 0}</strong>
                <span>数据库</span>
              </div>
              <div data-warning={(workspace.error_project_count ?? 0) > 0}>
                <strong>{workspace.error_project_count ?? 0}</strong>
                <span>异常</span>
              </div>
              <div>
                <strong>
                  {workspace.database_authorization_count ?? 0}
                </strong>
                <span>授权</span>
              </div>
            </div>
            <p className="refresh-time">
              最近更新：{formattedTime(workspace.updated_at)}
            </p>
            <div className="workspace-card-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={busyWorkspaceId === workspace.id}
                onClick={() => openEditor(workspace)}
              >
                编辑
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={busyWorkspaceId === workspace.id}
                onClick={() => void toggleWorkspace(workspace)}
              >
                {workspace.enabled ? "停用" : "启用"}
              </button>
              <button
                type="button"
                className="danger-text-button"
                disabled={busyWorkspaceId === workspace.id}
                onClick={() => setDeletingWorkspace(workspace)}
              >
                删除
              </button>
              <button
                type="button"
                className="primary-button"
                onClick={() => setActiveWorkspace(workspace)}
              >
                进入工作空间
              </button>
            </div>
          </article>
        ))}
      </section>

      {editor ? (
        <div className="project-settings-modal" role="presentation">
          <form
            className="management-modal workspace-editor"
            role="dialog"
            aria-modal="true"
            aria-label={editor === "new" ? "添加工作空间" : "编辑工作空间"}
            onSubmit={submitWorkspace}
          >
            <header>
              <div>
                <span className="file-chip">工作空间配置</span>
                <h2>{editor === "new" ? "添加工作空间" : "编辑工作空间"}</h2>
                <p>
                  根目录使用宿主机绝对路径；子项目只保存相对于此目录的路径。
                </p>
              </div>
              <button
                type="button"
                className="close-button"
                aria-label="关闭工作空间编辑"
                onClick={() => setEditor(null)}
              >
                ×
              </button>
            </header>
            <div className="management-form-grid">
              <label>
                工作空间名称
                <input
                  value={form.name}
                  onChange={(event) =>
                    setForm({ ...form, name: event.target.value })
                  }
                  placeholder="例如：Agent Context Router"
                  required
                />
              </label>
              <label>
                工作空间类型
                <input
                  value={form.workspaceType}
                  onChange={(event) =>
                    setForm({ ...form, workspaceType: event.target.value })
                  }
                  placeholder="例如：公司项目"
                  maxLength={60}
                  required
                />
              </label>
              <label className="wide-field">
                根目录绝对路径
                <input
                  value={form.rootPath}
                  onChange={(event) =>
                    setForm({ ...form, rootPath: event.target.value })
                  }
                  placeholder="/Users/name/workforce/company"
                  required
                />
              </label>
              {editor !== "new" ? (
                <label className="checkbox-field wide-field">
                  <input
                    type="checkbox"
                    checked={form.enabled}
                    onChange={(event) =>
                      setForm({ ...form, enabled: event.target.checked })
                    }
                  />
                  启用该工作空间及其 cwd 项目匹配
                </label>
              ) : null}
            </div>
            <footer>
              <button
                type="button"
                className="secondary-button"
                onClick={() => setEditor(null)}
              >
                取消
              </button>
              <button
                type="submit"
                className="primary-button"
                disabled={
                  busyWorkspaceId ===
                  (editor === "new" ? "new" : editor.id)
                }
              >
                {busyWorkspaceId ===
                (editor === "new" ? "new" : editor.id)
                  ? "正在保存…"
                  : editor === "new"
                    ? "创建工作空间"
                    : "保存配置"}
              </button>
            </footer>
          </form>
        </div>
      ) : null}

      {deletingWorkspace ? (
        <div className="project-settings-modal" role="presentation">
          <section
            className="project-delete-panel"
            role="alertdialog"
            aria-modal="true"
            aria-label={`删除工作空间 ${deletingWorkspace.name}`}
          >
            <span className="file-chip">删除工作空间配置</span>
            <h2>确定删除“{deletingWorkspace.name}”吗？</h2>
            <p>
              会同时删除 Context Router 中该工作空间下的项目配置、项目数据源授权和文档搜索索引；
              调用历史快照与磁盘目录会保留。配置删除后无法在页面中撤销。
            </p>
            <footer>
              <button
                type="button"
                className="secondary-button"
                onClick={() => setDeletingWorkspace(null)}
              >
                取消
              </button>
              <button
                type="button"
                className="danger-button"
                disabled={busyWorkspaceId === deletingWorkspace.id}
                onClick={() => void confirmDeletion()}
              >
                {busyWorkspaceId === deletingWorkspace.id
                  ? "正在删除…"
                  : "确认删除"}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}
