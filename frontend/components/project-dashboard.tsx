"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type {
  FormEvent,
  PointerEvent as ReactPointerEvent,
} from "react";

import { DocumentTree } from "@/components/document-tree";
import { MarkdownViewer } from "@/components/markdown-viewer";
import { McpIntegrationPanel } from "@/components/mcp-integration-panel";
import {
  createProject,
  deleteProject,
  getDocumentDetail,
  getProjectTree,
  getTaskDocumentReads,
  listProjects,
  listProjectTasks,
  prepareProjectPreview,
  refreshProject,
  setProjectEnabled,
  updateProject,
} from "@/lib/api";
import {
  buildDocumentCallNumbers,
  buildTaskReadRows,
  buildTaskReadSteps,
} from "@/lib/task-history";
import type {
  ContextTaskReadHistory,
  ContextTaskSummary,
  DocumentDetail,
  DocumentTreeNode,
  PrepareTaskContextResult,
  ProjectSummary,
} from "@/lib/types";

function formattedTime(value: string | null): string {
  if (!value) return "尚未刷新";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

interface DocumentDetailDrawerProps {
  detail: DocumentDetail | null;
  loading: boolean;
  onClose: () => void;
}

function DocumentDetailDrawer({
  detail,
  loading,
  onClose,
}: DocumentDetailDrawerProps) {
  return (
    <aside
      className="document-detail-drawer"
      role="dialog"
      aria-label="Markdown 文档详情"
    >
      <button
        type="button"
        className="close-button detail-close-button"
        aria-label="关闭文档详情"
        onClick={onClose}
      >
        ×
      </button>
      {loading ? (
        <p className="empty-message">正在读取内存中的文档内容…</p>
      ) : detail ? (
        <>
          <header className="document-detail-header">
            <div>
              <span className="file-chip">Markdown</span>
              <h2>{detail.description}</h2>
            </div>
            <code>{detail.relative_path ?? detail.path}</code>
          </header>
          {detail.error ? (
            <div className="error-banner">{detail.error}</div>
          ) : null}
          <MarkdownViewer content={detail.content} />
        </>
      ) : (
        <p className="empty-message">文档内容读取失败。</p>
      )}
    </aside>
  );
}

export function ProjectDashboard() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProject, setActiveProject] = useState<ProjectSummary | null>(null);
  const [tree, setTree] = useState<DocumentTreeNode | null>(null);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showMcpIntegration, setShowMcpIntegration] = useState(false);
  const [editingProject, setEditingProject] = useState<ProjectSummary | null>(
    null,
  );
  const [editName, setEditName] = useState("");
  const [editAgentsPath, setEditAgentsPath] = useState("");
  const [deletingProject, setDeletingProject] =
    useState<ProjectSummary | null>(null);
  const [actionsProject, setActionsProject] = useState<ProjectSummary | null>(
    null,
  );
  const [name, setName] = useState("");
  const [agentsPath, setAgentsPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [draggingTree, setDraggingTree] = useState(false);
  const [busyProjectId, setBusyProjectId] = useState<string | null>(null);
  const [mcpPreviewProject, setMcpPreviewProject] =
    useState<ProjectSummary | null>(null);
  const [mcpPreview, setMcpPreview] =
    useState<PrepareTaskContextResult | null>(null);
  const [historyProject, setHistoryProject] = useState<ProjectSummary | null>(
    null,
  );
  const [historyTasks, setHistoryTasks] = useState<ContextTaskSummary[]>([]);
  const [selectedHistoryTaskId, setSelectedHistoryTaskId] = useState<
    number | null
  >(null);
  const [history, setHistory] = useState<ContextTaskReadHistory | null>(null);
  const [historyTree, setHistoryTree] = useState<DocumentTreeNode | null>(null);
  const [historyView, setHistoryView] = useState<"tree" | "list">("tree");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [draggingHistory, setDraggingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const treeViewportRef = useRef<HTMLDivElement>(null);
  const historyViewportRef = useRef<HTMLElement>(null);
  const treeDragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    scrollLeft: number;
    scrollTop: number;
  } | null>(null);
  const historyDragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    scrollLeft: number;
    scrollTop: number;
  } | null>(null);

  const loadProjects = useCallback(async () => {
    setLoading(true);
    try {
      setProjects(await listProjects());
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    if (!activeProject || !tree) return;

    const frame = window.requestAnimationFrame(() => {
      const viewport = treeViewportRef.current;
      if (!viewport) return;
      viewport.scrollLeft = Math.max(
        0,
        (viewport.scrollWidth - viewport.clientWidth) / 2,
      );
      viewport.scrollTop = Math.min(90, viewport.scrollHeight);
    });

    return () => window.cancelAnimationFrame(frame);
  }, [activeProject, tree]);

  useEffect(() => {
    if (!historyProject || !history) return;

    const frame = window.requestAnimationFrame(() => {
      const viewport = historyViewportRef.current;
      if (!viewport) return;
      viewport.scrollLeft = Math.max(
        0,
        (viewport.scrollWidth - viewport.clientWidth) / 2,
      );
      viewport.scrollTop = 0;
    });

    return () => window.cancelAnimationFrame(frame);
  }, [historyProject, history]);

  async function loadTree(project: ProjectSummary) {
    setBusyProjectId(project.id);
    try {
      const nextTree = await getProjectTree(project.id);
      setActiveProject(project);
      setTree(nextTree);
      setDetail(null);
      setSelectedId(null);
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusyProjectId(null);
    }
  }

  async function selectDocument(
    project: ProjectSummary,
    documentId: string,
  ) {
    setSelectedId(documentId);
    setDetail(null);
    setDetailLoading(true);
    try {
      setDetail(await getDocumentDetail(project.id, documentId));
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setDetailLoading(false);
    }
  }

  async function refresh(project: ProjectSummary, reopenTree = false) {
    setBusyProjectId(project.id);
    try {
      const updated = await refreshProject(project.id);
      setProjects((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      if (reopenTree) {
        const nextTree = await getProjectTree(project.id);
        setActiveProject(updated);
        setTree(nextTree);
        setDetail(null);
        setSelectedId(null);
      }
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusyProjectId(null);
    }
  }

  async function showMcpPreview(project: ProjectSummary) {
    setBusyProjectId(project.id);
    setMcpPreviewProject(project);
    setMcpPreview(null);
    try {
      setMcpPreview(await prepareProjectPreview(project.id));
      setError(null);
    } catch (requestError) {
      setMcpPreviewProject(null);
      setError((requestError as Error).message);
    } finally {
      setBusyProjectId(null);
    }
  }

  async function selectHistoryTask(taskId: number) {
    setSelectedHistoryTaskId(taskId);
    setHistoryLoading(true);
    setHistory(null);
    closeDetail();
    try {
      setHistory(await getTaskDocumentReads(taskId));
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setHistoryLoading(false);
    }
  }

  async function showTaskHistory(project: ProjectSummary) {
    setBusyProjectId(project.id);
    setHistoryProject(project);
    setHistoryTasks([]);
    setSelectedHistoryTaskId(null);
    setHistory(null);
    setHistoryTree(null);
    setHistoryView("tree");
    closeDetail();
    setHistoryLoading(true);
    try {
      const [tasks, projectTree] = await Promise.all([
        listProjectTasks(project.id),
        getProjectTree(project.id),
      ]);
      setHistoryTasks(tasks);
      setHistoryTree(projectTree);
      const initialTask =
        tasks.find((task) => task.read_call_count > 0) ?? tasks[0];
      if (initialTask) {
        setSelectedHistoryTaskId(initialTask.task_id);
        setHistory(await getTaskDocumentReads(initialTask.task_id));
      }
      setError(null);
    } catch (requestError) {
      setHistoryProject(null);
      setError((requestError as Error).message);
    } finally {
      setHistoryLoading(false);
      setBusyProjectId(null);
    }
  }

  async function submitProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusyProjectId("new");
    try {
      const project = await createProject({
        name: name.trim(),
        agents_path: agentsPath.trim(),
      });
      setProjects((current) => [...current, project]);
      setName("");
      setAgentsPath("");
      setShowCreate(false);
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusyProjectId(null);
    }
  }

  function startEditingProject(project: ProjectSummary) {
    setEditingProject(project);
    setEditName(project.name);
    setEditAgentsPath(project.agents_path);
  }

  async function submitProjectUpdate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingProject) return;
    setBusyProjectId(editingProject.id);
    try {
      const updated = await updateProject(editingProject.id, {
        name: editName.trim(),
        agents_path: editAgentsPath.trim(),
      });
      setProjects((current) =>
        current.map((project) =>
          project.id === updated.id ? updated : project,
        ),
      );
      if (activeProject?.id === updated.id) closeTree();
      if (historyProject?.id === updated.id) closeTaskHistory();
      setEditingProject(null);
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusyProjectId(null);
    }
  }

  async function toggleProject(project: ProjectSummary) {
    setBusyProjectId(project.id);
    try {
      const updated = await setProjectEnabled(project.id, !project.enabled);
      setProjects((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      if (!updated.enabled && activeProject?.id === updated.id) closeTree();
      if (!updated.enabled && historyProject?.id === updated.id) {
        closeTaskHistory();
      }
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusyProjectId(null);
    }
  }

  async function confirmProjectDeletion() {
    if (!deletingProject) return;
    setBusyProjectId(deletingProject.id);
    try {
      await deleteProject(deletingProject.id);
      setProjects((current) =>
        current.filter((project) => project.id !== deletingProject.id),
      );
      if (activeProject?.id === deletingProject.id) closeTree();
      if (historyProject?.id === deletingProject.id) closeTaskHistory();
      setDeletingProject(null);
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusyProjectId(null);
    }
  }

  function closeTree() {
    setActiveProject(null);
    setTree(null);
    setDetail(null);
    setSelectedId(null);
  }

  function closeDetail() {
    setDetail(null);
    setSelectedId(null);
  }

  function closeMcpPreview() {
    setMcpPreviewProject(null);
    setMcpPreview(null);
  }

  function closeTaskHistory() {
    setHistoryProject(null);
    setHistoryTasks([]);
    setSelectedHistoryTaskId(null);
    setHistory(null);
    setHistoryTree(null);
    setHistoryView("tree");
    setHistoryLoading(false);
    closeDetail();
  }

  function startHistoryDrag(event: ReactPointerEvent<HTMLElement>) {
    if ((event.target as HTMLElement).closest("button, select")) return;

    const viewport = event.currentTarget;
    historyDragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: viewport.scrollLeft,
      scrollTop: viewport.scrollTop,
    };
    viewport.setPointerCapture(event.pointerId);
    setDraggingHistory(true);
  }

  function moveHistory(event: ReactPointerEvent<HTMLElement>) {
    const drag = historyDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;

    event.currentTarget.scrollLeft =
      drag.scrollLeft - (event.clientX - drag.startX);
    event.currentTarget.scrollTop =
      drag.scrollTop - (event.clientY - drag.startY);
  }

  function endHistoryDrag(event: ReactPointerEvent<HTMLElement>) {
    const drag = historyDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;

    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    historyDragRef.current = null;
    setDraggingHistory(false);
  }

  function startTreeDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest("button")) return;

    const viewport = event.currentTarget;
    treeDragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: viewport.scrollLeft,
      scrollTop: viewport.scrollTop,
    };
    viewport.setPointerCapture(event.pointerId);
    setDraggingTree(true);
  }

  function moveTree(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = treeDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;

    event.currentTarget.scrollLeft =
      drag.scrollLeft - (event.clientX - drag.startX);
    event.currentTarget.scrollTop =
      drag.scrollTop - (event.clientY - drag.startY);
  }

  function endTreeDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = treeDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;

    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    treeDragRef.current = null;
    setDraggingTree(false);
  }

  const selectedHistoryTask =
    historyTasks.find((task) => task.task_id === selectedHistoryTaskId) ?? null;
  const historySteps = history ? buildTaskReadSteps(history.calls) : [];
  const historyRows = history ? buildTaskReadRows(history.calls) : [];
  const historyCallNumbers = history
    ? buildDocumentCallNumbers(history.calls)
    : new Map<string, number[]>();

  return (
    <>
      <div className="page-actions">
        <button
          type="button"
          className="secondary-button"
          onClick={() => setShowMcpIntegration(true)}
        >
          MCP 接入
        </button>
        <button
          type="button"
          className="primary-button"
          onClick={() => setShowCreate((visible) => !visible)}
        >
          {showCreate ? "取消添加" : "添加项目"}
        </button>
      </div>

      {showCreate ? (
        <form className="create-project-form" onSubmit={submitProject}>
          <label>
            项目名称
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：攀枝花多式联运"
              required
            />
          </label>
          <label>
            AGENTS.md 绝对路径
            <input
              value={agentsPath}
              onChange={(event) => setAgentsPath(event.target.value)}
              placeholder="/Users/name/workforce/project/AGENTS.md"
              required
            />
          </label>
          <button
            type="submit"
            className="primary-button"
            disabled={busyProjectId === "new"}
          >
            {busyProjectId === "new" ? "正在建立映射…" : "创建并映射"}
          </button>
        </form>
      ) : null}

      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}

      {loading ? <p className="empty-message">正在读取项目…</p> : null}

      {!loading && projects.length === 0 ? (
        <div className="empty-state">
          <h2>还没有文档项目</h2>
          <p>添加一个 AGENTS.md 绝对路径，系统会立即递归建立内存映射。</p>
        </div>
      ) : null}

      <section className="project-grid" aria-label="文档项目列表">
        {projects.map((project) => (
          <article
            className="project-card"
            data-enabled={project.enabled}
            key={project.id}
          >
            <div className="project-card-heading">
              <div>
                <span className="file-chip">AGENTS.md</span>
                <h2>{project.name}</h2>
              </div>
              <div className="project-card-statuses">
                <span
                  className="project-status-chip"
                  data-enabled={project.enabled}
                >
                  {project.enabled ? "已启用" : "已停用"}
                </span>
                <span className="node-count">{project.node_count} 个节点</span>
              </div>
            </div>
            <code className="project-path">{project.agents_path}</code>
            <p className="refresh-time">
              最近映射：{formattedTime(project.refreshed_at)}
            </p>
            {project.error ? <p className="card-error">{project.error}</p> : null}
            <div className="project-card-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={busyProjectId === project.id}
                onClick={() => setActionsProject(project)}
              >
                更多操作
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={busyProjectId === project.id || !project.enabled}
                onClick={() => void showTaskHistory(project)}
              >
                查看调用记录
              </button>
              <button
                type="button"
                className="primary-button"
                disabled={busyProjectId === project.id || !project.enabled}
                onClick={() => void loadTree(project)}
              >
                {busyProjectId === project.id ? "正在读取…" : "查看文档树"}
              </button>
            </div>
          </article>
        ))}
      </section>

      {showMcpIntegration ? (
        <McpIntegrationPanel
          projects={projects}
          onClose={() => setShowMcpIntegration(false)}
        />
      ) : null}

      {actionsProject ? (
        <div className="project-settings-modal" role="presentation">
          <section
            className="project-actions-panel"
            role="dialog"
            aria-modal="true"
            aria-label={`更多操作 ${actionsProject.name}`}
          >
            <header>
              <div>
                <span className="file-chip">项目操作</span>
                <h2>{actionsProject.name}</h2>
                <code>{actionsProject.agents_path}</code>
              </div>
              <button
                type="button"
                className="close-button"
                aria-label="关闭更多操作"
                onClick={() => setActionsProject(null)}
              >
                ×
              </button>
            </header>
            <div className="project-actions-grid">
              <button
                type="button"
                className="secondary-button"
                onClick={() => {
                  setActionsProject(null);
                  startEditingProject(actionsProject);
                }}
              >
                编辑项目
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={busyProjectId === actionsProject.id}
                onClick={() => {
                  setActionsProject(null);
                  void toggleProject(actionsProject);
                }}
              >
                {actionsProject.enabled ? "停用项目" : "启用项目"}
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={
                  busyProjectId === actionsProject.id || !actionsProject.enabled
                }
                onClick={() => {
                  setActionsProject(null);
                  void refresh(actionsProject);
                }}
              >
                刷新映射
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={
                  busyProjectId === actionsProject.id || !actionsProject.enabled
                }
                onClick={() => {
                  setActionsProject(null);
                  void showMcpPreview(actionsProject);
                }}
              >
                查看 MCP JSON
              </button>
              <button
                type="button"
                className="danger-button project-actions-delete"
                disabled={busyProjectId === actionsProject.id}
                onClick={() => {
                  setActionsProject(null);
                  setDeletingProject(actionsProject);
                }}
              >
                删除项目
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {editingProject ? (
        <div className="project-settings-modal" role="presentation">
          <form
            className="project-settings-panel"
            role="dialog"
            aria-modal="true"
            aria-label={`编辑项目 ${editingProject.name}`}
            onSubmit={submitProjectUpdate}
          >
            <header>
              <div>
                <span className="file-chip">项目配置</span>
                <h2>编辑项目</h2>
                <p>保存前会重新读取 AGENTS.md 并验证完整文档树。</p>
              </div>
              <button
                type="button"
                className="close-button"
                aria-label="关闭项目编辑"
                onClick={() => setEditingProject(null)}
              >
                ×
              </button>
            </header>
            <label>
              项目名称
              <input
                value={editName}
                required
                onChange={(event) => setEditName(event.target.value)}
              />
            </label>
            <label>
              AGENTS.md 绝对路径
              <input
                value={editAgentsPath}
                required
                onChange={(event) => setEditAgentsPath(event.target.value)}
              />
            </label>
            <footer>
              <button
                type="button"
                className="secondary-button"
                onClick={() => setEditingProject(null)}
              >
                取消
              </button>
              <button
                type="submit"
                className="primary-button"
                disabled={busyProjectId === editingProject.id}
              >
                {busyProjectId === editingProject.id ? "正在验证…" : "保存配置"}
              </button>
            </footer>
          </form>
        </div>
      ) : null}

      {deletingProject ? (
        <div className="project-settings-modal" role="presentation">
          <section
            className="project-delete-panel"
            role="alertdialog"
            aria-modal="true"
            aria-label={`删除项目 ${deletingProject.name}`}
          >
            <span className="file-chip">删除项目配置</span>
            <h2>确定删除“{deletingProject.name}”吗？</h2>
            <p>
              只删除 Context Router 中保存的项目配置，不会删除磁盘上的 AGENTS.md、文档或历史 MCP 调用记录。
              如果这个路径仍由默认项目环境变量声明，后端下次启动时会重新创建它。
            </p>
            <footer>
              <button
                type="button"
                className="secondary-button"
                onClick={() => setDeletingProject(null)}
              >
                取消
              </button>
              <button
                type="button"
                className="danger-button"
                disabled={busyProjectId === deletingProject.id}
                onClick={() => void confirmProjectDeletion()}
              >
                {busyProjectId === deletingProject.id ? "正在删除…" : "确认删除"}
              </button>
            </footer>
          </section>
        </div>
      ) : null}

      {mcpPreviewProject ? (
        <div className="mcp-json-modal" role="presentation">
          <section
            className="mcp-json-panel"
            role="dialog"
            aria-modal="true"
            aria-label={`${mcpPreviewProject.name} MCP JSON`}
          >
            <header className="mcp-json-header">
              <div>
                <span className="file-chip">MCP JSON</span>
                <h2>{mcpPreviewProject.name}</h2>
                <p>与 prepare_task_context 工具返回的数据结构一致</p>
              </div>
              <button
                type="button"
                className="close-button"
                aria-label="关闭 MCP JSON"
                onClick={closeMcpPreview}
              >
                ×
              </button>
            </header>
            {mcpPreview ? (
              <pre className="mcp-json-output">
                <code>{JSON.stringify(mcpPreview, null, 2)}</code>
              </pre>
            ) : (
              <p className="empty-message">正在生成完整文档树 JSON…</p>
            )}
          </section>
        </div>
      ) : null}

      {historyProject ? (
        <div
          className="task-history-modal"
          role="dialog"
          aria-modal="true"
          aria-label={`${historyProject.name} MCP 调用记录`}
        >
          <header className="tree-toolbar-overlay">
            <div className="tree-project-summary task-history-summary">
              <h2>{historyProject.name}</h2>
              {selectedHistoryTask ? (
                <>
                  <p>
                    任务 #{selectedHistoryTask.task_id} · {history?.calls.length ?? 0} 次 MCP 调用 · {historySteps.length} 个读取步骤
                  </p>
                  <strong>{selectedHistoryTask.task}</strong>
                </>
              ) : (
                <p>当前项目还没有 MCP 任务</p>
              )}
            </div>
            <div className="tree-toolbar-actions">
              <div className="task-history-tabs" role="tablist" aria-label="调用记录视图">
                <button
                  type="button"
                  role="tab"
                  aria-selected={historyView === "tree"}
                  className="task-history-tab"
                  data-active={historyView === "tree"}
                  onClick={() => {
                    closeDetail();
                    setHistoryView("tree");
                  }}
                >
                  文档树
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={historyView === "list"}
                  className="task-history-tab"
                  data-active={historyView === "list"}
                  onClick={() => {
                    closeDetail();
                    setHistoryView("list");
                  }}
                >
                  调用列表
                </button>
              </div>
              {historyTasks.length > 0 ? (
                <label className="task-history-selector">
                  <span>切换任务</span>
                  <select
                    aria-label="切换 MCP 任务"
                    value={selectedHistoryTaskId ?? ""}
                    disabled={historyLoading}
                    onChange={(event) =>
                      void selectHistoryTask(Number(event.target.value))
                    }
                  >
                    {historyTasks.map((task) => (
                      <option value={task.task_id} key={task.task_id}>
                        #{task.task_id} · {task.agent_name ?? "未标记 Agent"} · {task.task}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <button
                type="button"
                className="close-button"
                aria-label="关闭 MCP 调用记录"
                onClick={closeTaskHistory}
              >
                ×
              </button>
            </div>
          </header>

          <section
            ref={historyViewportRef}
            className="task-history-viewport"
            data-dragging={draggingHistory}
            aria-label="可拖动的文档读取调用链"
            onPointerDown={startHistoryDrag}
            onPointerMove={moveHistory}
            onPointerUp={endHistoryDrag}
            onPointerCancel={endHistoryDrag}
          >
            <div
              className={`task-history-world task-history-${historyView}-world`}
            >
              {historyLoading ? (
                <p className="task-history-message">正在读取任务调用记录…</p>
              ) : null}
              {!historyLoading && historyTasks.length === 0 ? (
                <div className="empty-state task-history-empty">
                  <h3>当前项目还没有 MCP 任务</h3>
                </div>
              ) : null}
              {!historyLoading &&
              historyView === "list" &&
              history &&
              historySteps.length === 0 ? (
                <div className="empty-state task-history-empty">
                  <h3>这个任务还没有读取文档</h3>
                  <p>调用 read_context_document 后，记录会显示在这里。</p>
                </div>
              ) : null}
              {!historyLoading &&
              historyView === "list" &&
              historySteps.length > 0 ? (
                <div className="task-history-flow">
                  {historyRows.map((row) => (
                    <section
                      className="task-history-call-row"
                      aria-label={`第 ${row.callNumber} 次 MCP 调用`}
                      key={row.readCallId}
                    >
                      {row.steps.map((step) => (
                        <button
                          type="button"
                          className="task-history-node"
                          data-status={step.document.status}
                          disabled={step.document.status === "error"}
                          key={`${step.readCallId}-${step.document.position}`}
                          onClick={() =>
                            void selectDocument(
                              historyProject,
                              step.document.document_id,
                            )
                          }
                        >
                          <span
                            className="task-history-sequence"
                            aria-label={`调用顺序 ${step.sequence}`}
                          >
                            {step.sequence}
                          </span>
                          <span className="file-chip">
                            第 {step.callNumber} 次 MCP 调用
                          </span>
                          <strong>
                            {step.document.path ?? step.document.document_id}
                          </strong>
                          {step.document.section ? (
                            <small>章节：{step.document.section}</small>
                          ) : null}
                          <code>
                            read_call_id: {step.readCallId} · position: {step.document.position}
                          </code>
                          <small>{formattedTime(step.createdAt)}</small>
                          {step.document.status === "error" ? (
                            <small className="read-error">
                              读取失败：{step.document.error_code}
                            </small>
                          ) : (
                            <small>读取成功</small>
                          )}
                        </button>
                      ))}
                    </section>
                  ))}
                </div>
              ) : null}
              {!historyLoading &&
              historyView === "tree" &&
              historyTasks.length > 0 &&
              historyTree ? (
                <div className="tree-content">
                  <ul className="document-tree">
                    <DocumentTree
                      node={historyTree}
                      selectedId={selectedId}
                      onSelect={(node) =>
                        void selectDocument(historyProject, node.id)
                      }
                      callNumbersByDocumentId={historyCallNumbers}
                    />
                  </ul>
                </div>
              ) : null}
            </div>
          </section>

          {selectedId ? (
            <DocumentDetailDrawer
              detail={detail}
              loading={detailLoading}
              onClose={closeDetail}
            />
          ) : null}
        </div>
      ) : null}

      {activeProject && tree ? (
        <div className="tree-modal" role="dialog" aria-modal="true">
          <header className="tree-toolbar-overlay">
            <div className="tree-project-summary">
              <h2>{activeProject.name}</h2>
              <p>
                {activeProject.node_count} 个文档节点 · 按住空白区域拖动画布
              </p>
            </div>
            <div className="tree-toolbar-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={busyProjectId === activeProject.id}
                onClick={() => void refresh(activeProject, true)}
              >
                {busyProjectId === activeProject.id
                  ? "正在刷新…"
                  : "刷新整棵树"}
              </button>
              <button
                type="button"
                className="close-button"
                aria-label="关闭文档树"
                onClick={closeTree}
              >
                ×
              </button>
            </div>
          </header>

          <section
            ref={treeViewportRef}
            className="tree-viewport"
            data-dragging={draggingTree}
            aria-label="可拖动的递归文档树"
            onPointerDown={startTreeDrag}
            onPointerMove={moveTree}
            onPointerUp={endTreeDrag}
            onPointerCancel={endTreeDrag}
          >
            <div className="tree-world">
              <div className="tree-content">
                <ul className="document-tree">
                  <DocumentTree
                    node={tree}
                    selectedId={selectedId}
                    onSelect={(node) =>
                      void selectDocument(activeProject, node.id)
                    }
                  />
                </ul>
              </div>
            </div>
          </section>

          {selectedId ? (
            <DocumentDetailDrawer
              detail={detail}
              loading={detailLoading}
              onClose={closeDetail}
            />
          ) : null}
        </div>
      ) : null}
    </>
  );
}
