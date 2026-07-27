"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
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
  createWorkspaceProject,
  deleteWorkspaceProject,
  getProjectDataSourceOptions,
  getTaskDocumentReads,
  getWorkspaceDocumentDetail,
  getWorkspaceTree,
  listWorkspaceTasks,
  listWorkspaceProjects,
  prepareWorkspacePreview,
  refreshWorkspaceMapping,
  replaceProjectDatabases,
  updateWorkspaceProject,
} from "@/lib/api";
import {
  buildSelectedDatabaseAliases,
  buildTaskContextTimeline,
  validateDatabaseAliases,
} from "@/lib/database-access";
import {
  documentNodeLabel,
  resolveDocumentPath,
} from "@/lib/document-tree";
import { suggestProjectDocumentRelativePath } from "@/lib/project-paths";
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
  ProjectDataSourceOptions,
  ProjectKind,
  ProjectSummary,
  WorkspaceSummary,
} from "@/lib/types";

const ALL_DATA_SOURCE_CATEGORIES = "__all__";
const TREE_OVERVIEW_KEY = "__tree_overview__";

interface TreeScrollPosition {
  scrollLeft: number;
  scrollTop: number;
}

function treeViewKey(documentPath: readonly number[] | null): string {
  return documentPath
    ? `document-path:${documentPath.join(".")}`
    : TREE_OVERVIEW_KEY;
}

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
      <div className="document-detail-content">
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
      </div>
    </aside>
  );
}

interface DocumentTreeBreadcrumbsProps {
  path: DocumentTreeNode[];
  focusPath: readonly number[];
  onNavigate: (documentPath: number[] | null) => void;
}

function DocumentTreeBreadcrumbs({
  path,
  focusPath,
  onNavigate,
}: DocumentTreeBreadcrumbsProps) {
  return (
    <nav className="tree-breadcrumbs" aria-label="文档子树路径">
      <button type="button" onClick={() => onNavigate(null)}>
        ← 整棵树
      </button>
      {path.map((node, index) => {
        const current = index === path.length - 1;
        return (
          <span
            className="tree-breadcrumb-segment"
            key={`${node.id}-${index}`}
          >
            <span className="tree-breadcrumb-separator" aria-hidden="true">
              /
            </span>
            {current ? (
              <span aria-current="page">{documentNodeLabel(node)}</span>
            ) : (
              <button
                type="button"
                onClick={() => onNavigate(focusPath.slice(0, index))}
              >
                {documentNodeLabel(node)}
              </button>
            )}
          </span>
        );
      })}
    </nav>
  );
}

interface ProjectDashboardProps {
  workspace: WorkspaceSummary;
  projectKind: ProjectKind;
  visible?: boolean;
  onProjectCountsChanged?: (counts: Record<ProjectKind, number>) => void;
  onWorkspaceChanged?: () => Promise<void>;
}

export interface ProjectDashboardHandle {
  openCreateProject: () => void;
  refreshWorkspaceMapping: () => void;
  showWorkspaceTaskHistory: () => void;
  showWorkspaceTree: () => void;
  showWorkspaceMcpPreview: () => void;
  showMcpIntegration: () => void;
}

function projectKindLabel(kind: ProjectKind): string {
  return kind === "frontend" ? "前端项目" : "后端项目";
}

export const ProjectDashboard = forwardRef<
  ProjectDashboardHandle,
  ProjectDashboardProps
>(function ProjectDashboard(
  {
    workspace,
    projectKind,
    visible = true,
    onProjectCountsChanged,
    onWorkspaceChanged,
  }: ProjectDashboardProps,
  ref,
) {
  const workspaceId = workspace.id;
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProject, setActiveProject] = useState<ProjectSummary | null>(null);
  const [tree, setTree] = useState<DocumentTreeNode | null>(null);
  const [treeFocusPath, setTreeFocusPath] = useState<number[] | null>(null);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showMcpIntegration, setShowMcpIntegration] = useState(false);
  const [editingProject, setEditingProject] = useState<ProjectSummary | null>(
    null,
  );
  const [editName, setEditName] = useState("");
  const [editProjectKind, setEditProjectKind] =
    useState<ProjectKind>("backend");
  const [editRelativePath, setEditRelativePath] = useState("");
  const [editDocumentRelativePath, setEditDocumentRelativePath] = useState("");
  const [deletingProject, setDeletingProject] =
    useState<ProjectSummary | null>(null);
  const [dataSourceProject, setDataSourceProject] =
    useState<ProjectSummary | null>(null);
  const [dataSourceOptions, setDataSourceOptions] =
    useState<ProjectDataSourceOptions | null>(null);
  const [selectedDatabaseIds, setSelectedDatabaseIds] = useState<Set<string>>(
    new Set(),
  );
  const [databaseAliasDrafts, setDatabaseAliasDrafts] = useState<
    Record<string, string>
  >({});
  const [selectedDataSourceCategory, setSelectedDataSourceCategory] = useState(
    ALL_DATA_SOURCE_CATEGORIES,
  );
  const [activeDataSourceId, setActiveDataSourceId] = useState<string | null>(
    null,
  );
  const [dataSourceAccessLoading, setDataSourceAccessLoading] = useState(false);
  const [dataSourceAccessSaving, setDataSourceAccessSaving] = useState(false);
  const [name, setName] = useState("");
  const [newProjectKind, setNewProjectKind] =
    useState<ProjectKind>(projectKind);
  const [relativePath, setRelativePath] = useState("");
  const [documentRelativePath, setDocumentRelativePath] = useState("");
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
  const [historyTreeFocusPath, setHistoryTreeFocusPath] = useState<
    number[] | null
  >(
    null,
  );
  const [historyView, setHistoryView] = useState<"tree" | "list">("tree");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [draggingHistory, setDraggingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const treeViewportRef = useRef<HTMLDivElement>(null);
  const historyViewportRef = useRef<HTMLElement>(null);
  const treeScrollPositionsRef = useRef<Map<string, TreeScrollPosition>>(
    new Map(),
  );
  const historyScrollPositionsRef = useRef<Map<string, TreeScrollPosition>>(
    new Map(),
  );
  const treeFocusPendingRef = useRef(false);
  const historyTreeFocusPendingRef = useRef(false);
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
  const workspaceContextProject: ProjectSummary = {
    id: workspace.id,
    name: workspace.name,
    project_kind: projectKind,
    project_type: workspace.workspace_type,
    agents_path: `${workspace.root_path}/AGENTS.md`,
    document_relative_path: "AGENTS.md",
    workspace_id: workspace.id,
    workspace_name: workspace.name,
    workspace_enabled: workspace.enabled,
    relative_path: ".",
    node_count: projects.reduce(
      (total, project) => total + project.node_count,
      0,
    ),
    data_source_count: workspace.data_source_count,
    database_count: workspace.database_count,
    refreshed_at: null,
    error: null,
  };

  const loadProjects = useCallback(async () => {
    setLoading(true);
    try {
      const nextProjects = await listWorkspaceProjects(workspaceId);
      setProjects(nextProjects);
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    onProjectCountsChanged?.({
      frontend: projects.filter(
        (project) => project.project_kind === "frontend",
      ).length,
      backend: projects.filter(
        (project) => project.project_kind === "backend",
      ).length,
    });
  }, [onProjectCountsChanged, projects]);

  useEffect(() => {
    setNewProjectKind(projectKind);
  }, [projectKind]);

  useEffect(() => {
    if (!activeProject || !tree) return;

    const frame = window.requestAnimationFrame(() => {
      const viewport = treeViewportRef.current;
      if (!viewport) return;

      const savedPosition = treeScrollPositionsRef.current.get(
        treeViewKey(treeFocusPath),
      );
      if (savedPosition) {
        viewport.scrollLeft = savedPosition.scrollLeft;
        viewport.scrollTop = savedPosition.scrollTop;
      } else {
        viewport.scrollLeft = Math.max(
          0,
          (viewport.scrollWidth - viewport.clientWidth) / 2,
        );
        viewport.scrollTop = Math.min(90, viewport.scrollHeight);
      }

      if (treeFocusPendingRef.current) {
        viewport
          .querySelector<HTMLButtonElement>(
            ".document-tree > .document-tree-item > .document-node > .document-node-main",
          )
          ?.focus({ preventScroll: true });
        treeFocusPendingRef.current = false;
      }
    });

    return () => window.cancelAnimationFrame(frame);
  }, [activeProject, tree, treeFocusPath]);

  useEffect(() => {
    if (
      !historyProject ||
      !historyTree ||
      historyLoading ||
      historyView !== "tree"
    ) {
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      const viewport = historyViewportRef.current;
      if (!viewport) return;

      const savedPosition = historyScrollPositionsRef.current.get(
        treeViewKey(historyTreeFocusPath),
      );
      if (savedPosition) {
        viewport.scrollLeft = savedPosition.scrollLeft;
        viewport.scrollTop = savedPosition.scrollTop;
      } else {
        viewport.scrollLeft = Math.max(
          0,
          (viewport.scrollWidth - viewport.clientWidth) / 2,
        );
        viewport.scrollTop = 0;
      }

      if (historyTreeFocusPendingRef.current) {
        viewport
          .querySelector<HTMLButtonElement>(
            ".document-tree > .document-tree-item > .document-node > .document-node-main",
          )
          ?.focus({ preventScroll: true });
        historyTreeFocusPendingRef.current = false;
      }
    });

    return () => window.cancelAnimationFrame(frame);
  }, [
    historyLoading,
    historyProject,
    historyTree,
    historyTreeFocusPath,
    historyView,
  ]);

  async function loadTree(project: ProjectSummary) {
    setBusyProjectId("workspace");
    try {
      const nextTree = await getWorkspaceTree(workspace.id);
      setActiveProject(project);
      setTree(nextTree);
      setTreeFocusPath(null);
      treeScrollPositionsRef.current.clear();
      treeFocusPendingRef.current = false;
      setDetail(null);
      setSelectedId(null);
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusyProjectId(null);
    }
  }

  async function selectDocument(documentId: string) {
    setSelectedId(documentId);
    setDetail(null);
    setDetailLoading(true);
    try {
      setDetail(await getWorkspaceDocumentDetail(workspace.id, documentId));
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setDetailLoading(false);
    }
  }

  async function refresh(project: ProjectSummary, reopenTree = false) {
    setBusyProjectId("workspace");
    try {
      await refreshWorkspaceMapping(workspace.id);
      await loadProjects();
      await onWorkspaceChanged?.();
      if (reopenTree) {
        const nextTree = await getWorkspaceTree(workspace.id);
        setActiveProject(project);
        setTree(nextTree);
        setTreeFocusPath(null);
        treeScrollPositionsRef.current.clear();
        treeFocusPendingRef.current = false;
        setDetail(null);
        setSelectedId(null);
      }
      setError(null);
    } catch (requestError) {
      const refreshError = (requestError as Error).message;
      await Promise.allSettled([
        loadProjects(),
        onWorkspaceChanged?.() ?? Promise.resolve(),
      ]);
      setError(refreshError);
    } finally {
      setBusyProjectId(null);
    }
  }

  async function showMcpPreview(project: ProjectSummary) {
    setBusyProjectId("workspace");
    setMcpPreviewProject(project);
    setMcpPreview(null);
    try {
      setMcpPreview(await prepareWorkspacePreview(workspace.id));
      setError(null);
    } catch (requestError) {
      setMcpPreviewProject(null);
      setError((requestError as Error).message);
    } finally {
      setBusyProjectId(null);
    }
  }

  async function openProjectDataSources(project: ProjectSummary) {
    setDataSourceProject(project);
    setDataSourceOptions(null);
    setSelectedDatabaseIds(new Set());
    setSelectedDataSourceCategory(ALL_DATA_SOURCE_CATEGORIES);
    setActiveDataSourceId(null);
    setDataSourceAccessLoading(true);
    try {
      const options = await getProjectDataSourceOptions(project.id);
      const selectedIds = new Set(
        options.sources.flatMap((source) =>
          source.databases
            .filter((database) => database.selected)
            .map((database) => database.id),
        ),
      );
      const initialSource =
        options.sources.find((source) =>
          source.databases.some((database) => selectedIds.has(database.id)),
        ) ?? options.sources[0];
      setDataSourceOptions(options);
      setSelectedDatabaseIds(selectedIds);
      setDatabaseAliasDrafts(
        Object.fromEntries(
          options.sources.flatMap((source) =>
            source.databases
              .filter((database) => database.link_id && database.mcp_alias)
              .map((database) => [database.id, database.mcp_alias as string]),
          ),
        ),
      );
      setActiveDataSourceId(initialSource?.id ?? null);
      setError(null);
    } catch (requestError) {
      setDataSourceProject(null);
      setError((requestError as Error).message);
    } finally {
      setDataSourceAccessLoading(false);
    }
  }

  function closeProjectDataSources() {
    if (dataSourceAccessSaving) return;
    setDataSourceProject(null);
    setDataSourceOptions(null);
    setSelectedDatabaseIds(new Set());
    setDatabaseAliasDrafts({});
    setSelectedDataSourceCategory(ALL_DATA_SOURCE_CATEGORIES);
    setActiveDataSourceId(null);
  }

  function selectDataSourceCategory(category: string) {
    setSelectedDataSourceCategory(category);
    if (!dataSourceOptions) return;
    const visibleSources =
      category === ALL_DATA_SOURCE_CATEGORIES
        ? dataSourceOptions.sources
        : dataSourceOptions.sources.filter(
            (source) => source.category === category,
          );
    if (!visibleSources.some((source) => source.id === activeDataSourceId)) {
      setActiveDataSourceId(visibleSources[0]?.id ?? null);
    }
  }

  function toggleProjectDatabase(databaseId: string) {
    setSelectedDatabaseIds((current) => {
      const next = new Set(current);
      if (next.has(databaseId)) next.delete(databaseId);
      else next.add(databaseId);
      return next;
    });
  }

  function selectAllSourceDatabases(sourceId: string) {
    if (!dataSourceOptions) return;
    const source = dataSourceOptions.sources.find((item) => item.id === sourceId);
    if (!source?.enabled) return;
    setSelectedDatabaseIds((current) => {
      const next = new Set(current);
      source.databases.forEach((database) => {
        if (database.available) next.add(database.id);
      });
      return next;
    });
  }

  function clearSourceDatabases(sourceId: string) {
    if (!dataSourceOptions) return;
    const source = dataSourceOptions.sources.find((item) => item.id === sourceId);
    if (!source) return;
    setSelectedDatabaseIds((current) => {
      const next = new Set(current);
      source.databases.forEach((database) => next.delete(database.id));
      return next;
    });
  }

  async function saveProjectDataSources() {
    if (!dataSourceProject) return;
    if (Object.keys(databaseAliasErrors).length > 0) {
      setError("请先修正 MCP 别名格式或重复问题。");
      return;
    }
    setDataSourceAccessSaving(true);
    try {
      const mcpAliases = buildSelectedDatabaseAliases(
        selectedDatabaseIds,
        databaseAliasDrafts,
      );
      await replaceProjectDatabases(
        dataSourceProject.id,
        Array.from(selectedDatabaseIds),
        mcpAliases,
      );
      await loadProjects();
      await onWorkspaceChanged?.();
      setError(null);
      setDataSourceProject(null);
      setDataSourceOptions(null);
      setSelectedDatabaseIds(new Set());
      setDatabaseAliasDrafts({});
      setSelectedDataSourceCategory(ALL_DATA_SOURCE_CATEGORIES);
      setActiveDataSourceId(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setDataSourceAccessSaving(false);
    }
  }

  async function selectHistoryTask(taskId: number) {
    rememberHistoryTreeScrollPosition();
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
    setBusyProjectId("workspace");
    setHistoryProject(project);
    setHistoryTasks([]);
    setSelectedHistoryTaskId(null);
    setHistory(null);
    setHistoryTree(null);
    setHistoryTreeFocusPath(null);
    historyScrollPositionsRef.current.clear();
    historyTreeFocusPendingRef.current = false;
    setHistoryView("tree");
    closeDetail();
    setHistoryLoading(true);
    try {
      const [tasks, projectTree] = await Promise.all([
        listWorkspaceTasks(workspace.id),
        getWorkspaceTree(workspace.id),
      ]);
      setHistoryTasks(tasks);
      setHistoryTree(projectTree);
      const initialTask = tasks[0];
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

  function changeNewProjectKind(nextKind: ProjectKind) {
    const currentSuggestion = suggestProjectDocumentRelativePath(
      newProjectKind,
      relativePath,
    );
    setNewProjectKind(nextKind);
    setDocumentRelativePath((current) =>
      !current || current === currentSuggestion
        ? suggestProjectDocumentRelativePath(nextKind, relativePath)
        : current,
    );
  }

  function changeNewProjectRelativePath(nextPath: string) {
    const currentSuggestion = suggestProjectDocumentRelativePath(
      newProjectKind,
      relativePath,
    );
    setRelativePath(nextPath);
    setDocumentRelativePath((current) =>
      !current || current === currentSuggestion
        ? suggestProjectDocumentRelativePath(newProjectKind, nextPath)
        : current,
    );
  }

  async function submitProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusyProjectId("new");
    try {
      const project = await createWorkspaceProject(workspace.id, {
        name: name.trim(),
        relative_path: relativePath.trim(),
        document_relative_path: documentRelativePath.trim(),
        project_kind: newProjectKind,
      });
      setProjects((current) => [...current, project]);
      await onWorkspaceChanged?.();
      setName("");
      setNewProjectKind(projectKind);
      setRelativePath("");
      setDocumentRelativePath("");
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
    setEditProjectKind(project.project_kind);
    setEditRelativePath(project.relative_path ?? ".");
    setEditDocumentRelativePath(project.document_relative_path);
  }

  async function submitProjectUpdate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingProject) return;
    setBusyProjectId(editingProject.id);
    try {
      const updated = await updateWorkspaceProject(
        workspace.id,
        editingProject.id,
        {
          name: editName.trim(),
          relative_path: editRelativePath.trim(),
          document_relative_path: editDocumentRelativePath.trim(),
          project_kind: editProjectKind,
        },
      );
      setProjects((current) =>
        current.map((project) =>
          project.id === updated.id ? updated : project,
        ),
      );
      await onWorkspaceChanged?.();
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

  async function confirmProjectDeletion() {
    if (!deletingProject) return;
    setBusyProjectId(deletingProject.id);
    try {
      await deleteWorkspaceProject(workspace.id, deletingProject.id);
      setProjects((current) =>
        current.filter((project) => project.id !== deletingProject.id),
      );
      await onWorkspaceChanged?.();
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
    setTreeFocusPath(null);
    treeScrollPositionsRef.current.clear();
    treeFocusPendingRef.current = false;
    setDetail(null);
    setSelectedId(null);
  }

  function closeDetail() {
    setDetail(null);
    setSelectedId(null);
  }

  function openTreeSubtree(documentPath: readonly number[]) {
    const viewport = treeViewportRef.current;
    if (viewport) {
      treeScrollPositionsRef.current.set(treeViewKey(treeFocusPath), {
        scrollLeft: viewport.scrollLeft,
        scrollTop: viewport.scrollTop,
      });
    }
    closeDetail();
    treeFocusPendingRef.current = true;
    setTreeFocusPath([...documentPath]);
  }

  function navigateTreeSubtree(documentPath: number[] | null) {
    const viewport = treeViewportRef.current;
    if (viewport) {
      treeScrollPositionsRef.current.set(treeViewKey(treeFocusPath), {
        scrollLeft: viewport.scrollLeft,
        scrollTop: viewport.scrollTop,
      });
    }
    closeDetail();
    treeFocusPendingRef.current = true;
    setTreeFocusPath(documentPath);
  }

  function rememberHistoryTreeScrollPosition() {
    if (historyView !== "tree") return;
    const viewport = historyViewportRef.current;
    if (!viewport) return;
    historyScrollPositionsRef.current.set(treeViewKey(historyTreeFocusPath), {
      scrollLeft: viewport.scrollLeft,
      scrollTop: viewport.scrollTop,
    });
  }

  function openHistorySubtree(documentPath: readonly number[]) {
    rememberHistoryTreeScrollPosition();
    closeDetail();
    historyTreeFocusPendingRef.current = true;
    setHistoryTreeFocusPath([...documentPath]);
  }

  function navigateHistorySubtree(documentPath: number[] | null) {
    rememberHistoryTreeScrollPosition();
    closeDetail();
    historyTreeFocusPendingRef.current = true;
    setHistoryTreeFocusPath(documentPath);
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
    setHistoryTreeFocusPath(null);
    historyScrollPositionsRef.current.clear();
    historyTreeFocusPendingRef.current = false;
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

  const treeBreadcrumbPath =
    tree && treeFocusPath !== null
      ? (resolveDocumentPath(tree, treeFocusPath) ?? [])
      : [];
  const focusedTreeNode = treeBreadcrumbPath.at(-1) ?? tree;
  const historyTreeBreadcrumbPath =
    historyTree && historyTreeFocusPath !== null
      ? (resolveDocumentPath(historyTree, historyTreeFocusPath) ?? [])
      : [];
  const focusedHistoryTreeNode =
    historyTreeBreadcrumbPath.at(-1) ?? historyTree;
  const selectedHistoryTask =
    historyTasks.find((task) => task.task_id === selectedHistoryTaskId) ?? null;
  const historySteps = history ? buildTaskReadSteps(history.calls) : [];
  const historyRows = history ? buildTaskReadRows(history.calls) : [];
  const historyTimeline = history
    ? buildTaskContextTimeline(historyRows, history.database_calls)
    : [];
  const historyCallNumbers = history
    ? buildDocumentCallNumbers(history.calls)
    : new Map<string, number[]>();
  const visibleProjects = projects.filter(
    (project) => project.project_kind === projectKind,
  );
  const dataSourceCategories = dataSourceOptions
    ? Array.from(
        new Set(dataSourceOptions.sources.map((source) => source.category)),
      ).sort((left, right) => left.localeCompare(right, "zh-CN"))
    : [];
  const visibleDataSources = dataSourceOptions
    ? selectedDataSourceCategory === ALL_DATA_SOURCE_CATEGORIES
      ? dataSourceOptions.sources
      : dataSourceOptions.sources.filter(
          (source) => source.category === selectedDataSourceCategory,
        )
    : [];
  const activeDataSource =
    visibleDataSources.find((source) => source.id === activeDataSourceId) ??
    visibleDataSources[0] ??
    null;
  const selectedDataSourceCount = dataSourceOptions
    ? dataSourceOptions.sources.filter((source) =>
        source.databases.some((database) =>
          selectedDatabaseIds.has(database.id),
        ),
      ).length
    : 0;
  const databaseAliasErrors = validateDatabaseAliases(
    dataSourceOptions
      ? dataSourceOptions.sources.flatMap((source) =>
          source.databases
            .filter((database) => selectedDatabaseIds.has(database.id))
            .map((database) => ({
              databaseId: database.id,
              value:
                databaseAliasDrafts[database.id] ?? database.mcp_alias ?? "",
              required: Boolean(database.link_id),
            })),
        )
      : [],
  );

  useImperativeHandle(ref, () => ({
    openCreateProject() {
      setNewProjectKind(projectKind);
      setShowCreate(true);
    },
    refreshWorkspaceMapping() {
      void refresh(workspaceContextProject);
    },
    showWorkspaceTaskHistory() {
      void showTaskHistory(workspaceContextProject);
    },
    showWorkspaceTree() {
      void loadTree(workspaceContextProject);
    },
    showWorkspaceMcpPreview() {
      void showMcpPreview(workspaceContextProject);
    },
    showMcpIntegration() {
      setShowMcpIntegration(true);
    },
  }));

  return (
    <>
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}

      {visible ? (
        <>
          {showCreate ? (
            <form
              className="create-project-form workspace-project-form"
              onSubmit={submitProject}
            >
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
                项目类型
                <select
                  value={newProjectKind}
                  onChange={(event) =>
                    changeNewProjectKind(event.target.value as ProjectKind)
                  }
                >
                  <option value="frontend">前端项目</option>
                  <option value="backend">后端项目</option>
                </select>
              </label>
              <label>
                源码相对路径
                <input
                  value={relativePath}
                  onChange={(event) =>
                    changeNewProjectRelativePath(event.target.value)
                  }
                  placeholder="例如：backend/c12-mtp；根项目填写 ."
                  required
                />
              </label>
              <label>
                文档入口相对路径
                <input
                  value={documentRelativePath}
                  onChange={(event) =>
                    setDocumentRelativePath(event.target.value)
                  }
                  placeholder={`docs/${newProjectKind}/项目目录名/AGENTS.md`}
                  required
                />
                <small>
                  默认约定：docs/{newProjectKind}/项目目录名/AGENTS.md
                </small>
              </label>
              <div className="create-project-actions">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={busyProjectId === "new"}
                  onClick={() => setShowCreate(false)}
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="primary-button"
                  disabled={busyProjectId === "new"}
                >
                  {busyProjectId === "new" ? "正在建立映射…" : "创建并映射"}
                </button>
              </div>
            </form>
          ) : null}

          {loading ? <p className="empty-message">正在读取项目…</p> : null}

          {!loading && projects.length === 0 ? (
            <div className="empty-state">
              <h2>这个工作空间还没有项目</h2>
              <p>
                分别配置源码目录和 docs 下的文档入口，系统会从文档入口建立映射。
              </p>
            </div>
          ) : null}

          {!loading && projects.length > 0 && visibleProjects.length === 0 ? (
            <div className="empty-state">
              <h2>{`还没有${projectKindLabel(projectKind)}`}</h2>
              <p>添加项目时可以选择前端项目或后端项目。</p>
            </div>
          ) : null}

          <section className="project-grid" aria-label="文档项目列表">
            {visibleProjects.map((project) => (
              <article className="project-card" key={project.id}>
                <div className="project-card-heading">
                  <div>
                    <div className="project-card-chips">
                      <span className="project-type-chip">
                        {projectKindLabel(project.project_kind)}
                      </span>
                      <span className="project-type-chip">
                        {project.relative_path === "."
                          ? "根项目"
                          : (project.relative_path ?? "相对路径未返回")}
                      </span>
                    </div>
                    <h2>{project.name}</h2>
                  </div>
                  <div className="project-card-statuses">
                    <span className="node-count">
                      {project.node_count} 个节点
                    </span>
                    <span className="node-count">
                      {project.database_count ?? 0} 个数据库
                    </span>
                  </div>
                </div>
                <div className="project-path">
                  <div>
                    源码：<code>{project.relative_path ?? "."}</code>
                  </div>
                  <div>
                    文档：<code>{project.document_relative_path}</code>
                  </div>
                </div>
                <p className="refresh-time">
                  最近映射：{formattedTime(project.refreshed_at)}
                </p>
                {project.error ? (
                  <p className="card-error">{project.error}</p>
                ) : null}
                <div className="project-card-actions">
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={busyProjectId === project.id}
                    onClick={() => startEditingProject(project)}
                  >
                    编辑项目
                  </button>
                  <button
                    type="button"
                    className="primary-button"
                    disabled={busyProjectId === project.id}
                    onClick={() => void openProjectDataSources(project)}
                  >
                    管理数据源
                  </button>
                  <button
                    type="button"
                    className="danger-button"
                    disabled={busyProjectId === project.id}
                    onClick={() => setDeletingProject(project)}
                  >
                    删除项目
                  </button>
                </div>
              </article>
            ))}
          </section>
        </>
      ) : null}

      {showMcpIntegration ? (
        <McpIntegrationPanel
          workspace={workspace}
          onClose={() => setShowMcpIntegration(false)}
        />
      ) : null}

      {dataSourceProject ? (
        <div
          className="project-settings-modal project-data-source-modal"
          role="presentation"
        >
          <section
            className="project-data-source-panel"
            role="dialog"
            aria-modal="true"
            aria-label={`管理项目数据源 ${dataSourceProject.name}`}
          >
            <header>
              <span className="file-chip">数据源授权</span>
              <button
                type="button"
                className="close-button"
                aria-label="关闭项目数据源管理"
                disabled={dataSourceAccessSaving}
                onClick={closeProjectDataSources}
              >
                ×
              </button>
            </header>

            {dataSourceAccessLoading ? (
              <p className="empty-message">正在读取数据源和数据库清单…</p>
            ) : dataSourceOptions ? (
              <>
                <div className="project-data-source-summary">
                  <div>
                    <strong>
                      已选择 {selectedDataSourceCount} 个数据源 · {selectedDatabaseIds.size} 个数据库
                    </strong>
                    <span>
                      保存后整批替换当前项目关联，新关联默认只读；历史关联若不是只读，不会向 MCP 暴露。
                    </span>
                    {Object.keys(databaseAliasErrors).length > 0 ? (
                      <span className="database-alias-summary-error" role="alert">
                        有 {Object.keys(databaseAliasErrors).length} 个 MCP 别名需要修正
                      </span>
                    ) : null}
                  </div>
                </div>

                {dataSourceOptions.sources.length > 0 ? (
                  <>
                    <nav
                      className="data-source-category-tabs project-data-source-tabs"
                      role="tablist"
                      aria-label="数据源分类"
                    >
                      <button
                        type="button"
                        role="tab"
                        aria-selected={
                          selectedDataSourceCategory ===
                          ALL_DATA_SOURCE_CATEGORIES
                        }
                        data-active={
                          selectedDataSourceCategory ===
                          ALL_DATA_SOURCE_CATEGORIES
                        }
                        onClick={() =>
                          selectDataSourceCategory(ALL_DATA_SOURCE_CATEGORIES)
                        }
                      >
                        <span>全部数据源</span>
                        <small>{dataSourceOptions.sources.length}</small>
                      </button>
                      {dataSourceCategories.map((category) => (
                        <button
                          type="button"
                          role="tab"
                          aria-selected={
                            selectedDataSourceCategory === category
                          }
                          data-active={selectedDataSourceCategory === category}
                          key={category}
                          onClick={() => selectDataSourceCategory(category)}
                        >
                          <span>{category}</span>
                          <small>
                            {
                              dataSourceOptions.sources.filter(
                                (source) => source.category === category,
                              ).length
                            }
                          </small>
                        </button>
                      ))}
                    </nav>

                    <div className="project-data-source-layout">
                      <aside
                        className="project-source-selector"
                        aria-label="选择数据源"
                      >
                        {visibleDataSources.map((source) => {
                          const selectedCount = source.databases.filter(
                            (database) =>
                              selectedDatabaseIds.has(database.id),
                          ).length;
                          return (
                            <button
                              type="button"
                              data-active={activeDataSource?.id === source.id}
                              key={source.id}
                              onClick={() => setActiveDataSourceId(source.id)}
                            >
                              <span>
                                <strong>{source.name}</strong>
                                <small>
                                  {source.engine.toUpperCase()} · {source.databases.length} 个数据库
                                </small>
                              </span>
                              <span className="project-source-count">
                                {selectedCount}
                              </span>
                            </button>
                          );
                        })}
                      </aside>

                      <section className="project-database-selector">
                        {activeDataSource ? (
                          <>
                            <header>
                              <div>
                                <h3>{activeDataSource.name}</h3>
                                <p>
                                  {activeDataSource.category} · {activeDataSource.enabled ? "连接已启用" : "连接已停用"}
                                </p>
                              </div>
                              <div className="project-database-actions">
                                <button
                                  type="button"
                                  className="secondary-button"
                                  disabled={!activeDataSource.enabled}
                                  onClick={() =>
                                    selectAllSourceDatabases(activeDataSource.id)
                                  }
                                >
                                  全选可用库
                                </button>
                                <button
                                  type="button"
                                  className="secondary-button"
                                  onClick={() =>
                                    clearSourceDatabases(activeDataSource.id)
                                  }
                                >
                                  清空当前
                                </button>
                              </div>
                            </header>

                            {activeDataSource.databases.length > 0 ? (
                              <div className="project-database-options">
                                {activeDataSource.databases.map((database) => {
                                  const selected = selectedDatabaseIds.has(
                                    database.id,
                                  );
                                  const unavailable =
                                    !activeDataSource.enabled ||
                                    !database.available;
                                  return (
                                    <div
                                      className="project-database-option"
                                      data-disabled={!selected && unavailable}
                                      data-selected={selected}
                                      key={database.id}
                                    >
                                      <input
                                        id={`project-database-${database.id}`}
                                        type="checkbox"
                                        checked={selected}
                                        disabled={!selected && unavailable}
                                        aria-label={`选择 ${database.display_name || database.remote_name}`}
                                        onChange={() =>
                                          toggleProjectDatabase(database.id)
                                        }
                                      />
                                      <div className="project-database-option-main">
                                        <label htmlFor={`project-database-${database.id}`}>
                                          <strong>{database.display_name || database.remote_name}</strong>
                                          <code>{database.remote_name}</code>
                                        </label>
                                        {selected ? (
                                          <label className="database-alias-field">
                                            <span>MCP 别名</span>
                                          <input
                                            aria-label={`${database.display_name || database.remote_name} MCP 别名`}
                                            aria-invalid={Boolean(databaseAliasErrors[database.id])}
                                            aria-describedby={
                                              databaseAliasErrors[database.id]
                                                ? `database-alias-error-${database.id}`
                                                : undefined
                                            }
                                            className="database-alias-input"
                                            maxLength={64}
                                            value={databaseAliasDrafts[database.id] ?? database.mcp_alias ?? ""}
                                            onChange={(event) =>
                                              setDatabaseAliasDrafts((current) => ({
                                                ...current,
                                                [database.id]: event.target.value,
                                              }))
                                            }
                                            placeholder={database.link_id ? "MCP 别名" : "留空则自动生成"}
                                          />
                                            {databaseAliasErrors[database.id] ? (
                                              <small
                                                className="database-alias-error"
                                                id={`database-alias-error-${database.id}`}
                                              >
                                                {databaseAliasErrors[database.id]}
                                              </small>
                                            ) : null}
                                          </label>
                                        ) : null}
                                      </div>
                                      <small>
                                        {database.available ? database.namespace_type : "不可用"}
                                      </small>
                                    </div>
                                  );
                                })}
                              </div>
                            ) : (
                              <div className="project-data-source-empty">
                                <h3>这个数据源还没有数据库清单</h3>
                                <p>请先到数据源管理中测试连接并刷新数据库。</p>
                              </div>
                            )}
                          </>
                        ) : (
                          <div className="project-data-source-empty">
                            <h3>当前分类下没有数据源</h3>
                          </div>
                        )}
                      </section>
                    </div>
                  </>
                ) : (
                  <div className="project-data-source-empty">
                    <h3>还没有可选择的数据源</h3>
                    <p>请先到数据源管理中添加连接并刷新数据库清单。</p>
                  </div>
                )}

                <footer>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={dataSourceAccessSaving}
                    onClick={closeProjectDataSources}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="primary-button"
                    disabled={
                      dataSourceAccessSaving ||
                      Object.keys(databaseAliasErrors).length > 0
                    }
                    onClick={() => void saveProjectDataSources()}
                  >
                    {dataSourceAccessSaving ? "正在保存…" : "保存关联"}
                  </button>
                </footer>
              </>
            ) : null}
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
                <p>保存前会从 docs 下的文档入口重新读取并验证完整文档树。</p>
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
              项目类型
              <select
                value={editProjectKind}
                onChange={(event) =>
                  setEditProjectKind(event.target.value as ProjectKind)
                }
              >
                <option value="frontend">前端项目</option>
                <option value="backend">后端项目</option>
              </select>
            </label>
            <label>
              源码相对路径
              <input
                value={editRelativePath}
                required
                onChange={(event) => setEditRelativePath(event.target.value)}
              />
            </label>
            <label>
              文档入口相对路径
              <input
                value={editDocumentRelativePath}
                required
                placeholder={`docs/${editProjectKind}/项目目录名/AGENTS.md`}
                onChange={(event) =>
                  setEditDocumentRelativePath(event.target.value)
                }
              />
              <small>
                默认约定：docs/{editProjectKind}/项目目录名/AGENTS.md
              </small>
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
              只删除 Context Router 中保存的项目配置，不会删除源码目录、docs
              下的文档或历史 MCP 调用记录。
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
              <p className="empty-message">正在生成工作空间文档树 JSON…</p>
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
                    任务 #{selectedHistoryTask.task_id} · {(history?.calls.length ?? 0) + (history?.database_calls.length ?? 0)} 次 MCP 调用 · {historySteps.length} 个文档读取步骤
                  </p>
                  <strong>{selectedHistoryTask.task}</strong>
                </>
              ) : (
                <p>
                  {workspace
                    ? "当前工作空间还没有上下文调用任务"
                    : "当前项目还没有文档读取任务"}
                </p>
              )}
              {historyView === "tree" &&
              historyTreeFocusPath !== null &&
              historyTreeBreadcrumbPath.length > 0 ? (
                <DocumentTreeBreadcrumbs
                  path={historyTreeBreadcrumbPath}
                  focusPath={historyTreeFocusPath}
                  onNavigate={navigateHistorySubtree}
                />
              ) : null}
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
                    rememberHistoryTreeScrollPosition();
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
                  <h3>
                    {workspace
                      ? "当前工作空间还没有上下文调用任务"
                      : "当前项目还没有文档读取任务"}
                  </h3>
                </div>
              ) : null}
              {!historyLoading &&
              historyView === "list" &&
              history &&
              historySteps.length === 0 &&
              history.database_calls.length === 0 ? (
                <div className="empty-state task-history-empty">
                  <h3>这个任务还没有上下文调用</h3>
                  <p>读取文档或查询数据库后，记录会显示在这里。</p>
                </div>
              ) : null}
              {!historyLoading &&
              historyView === "list" &&
              history &&
              (historySteps.length > 0 || history.database_calls.length > 0) ? (
                <div className="task-history-flow">
                  {historyTimeline.map((item) => {
                    if (item.kind === "read") {
                      return (
                        <section
                          className="task-history-call-row"
                          aria-label={`第 ${item.eventNumber} 次上下文调用：文档读取`}
                          key={`read-${item.row.readCallId}`}
                        >
                          {item.row.steps.map((step) => (
                            <button
                              type="button"
                              className="task-history-node"
                              data-status={step.document.status}
                              disabled={step.document.status === "error"}
                              key={`${step.readCallId}-${step.document.position}`}
                              onClick={() =>
                                void selectDocument(step.document.document_id)
                              }
                            >
                              <span
                                className="task-history-sequence"
                                aria-label={`文档读取顺序 ${step.sequence}`}
                              >
                                {step.sequence}
                              </span>
                              <span className="file-chip">
                                第 {item.eventNumber} 次上下文调用 · 文档读取
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
                      );
                    }

                    const call = item.call;
                    return (
                      <section
                        className="task-history-call-row"
                        aria-label={`第 ${item.eventNumber} 次上下文调用：数据库调用`}
                        key={`database-${call.database_call_id}`}
                      >
                        <article
                          className="task-history-node"
                          data-status={call.status === "ok" ? "ok" : "error"}
                        >
                          <span className="file-chip">
                            第 {item.eventNumber} 次上下文调用 · 数据库
                          </span>
                          <strong>
                            {call.operation === "search_objects"
                              ? "搜索数据库对象"
                              : "执行只读查询"}
                            {" · "}
                            {call.database}
                          </strong>
                          <small>
                            {call.engine.toUpperCase()} · {call.object_type ?? call.statement_type ?? "只读操作"}
                          </small>
                          <code>
                            database_call_id: {call.database_call_id} · 返回 {call.returned_count ?? 0} 项
                          </code>
                          <small>
                            {formattedTime(call.created_at)} · {call.duration_ms ?? 0} ms · {call.result_bytes ?? 0} bytes
                          </small>
                          {call.status === "error" ? (
                            <small className="read-error">
                              调用失败：{call.error_code ?? "unknown_error"}
                            </small>
                          ) : call.truncated ? (
                            <small>结果已按安全预算截断</small>
                          ) : (
                            <small>调用成功</small>
                          )}
                        </article>
                      </section>
                    );
                  })}
                </div>
              ) : null}
              {!historyLoading &&
              historyView === "tree" &&
              historyTasks.length > 0 &&
              focusedHistoryTreeNode ? (
                <div className="tree-content">
                  <ul className="document-tree">
                    <DocumentTree
                      node={focusedHistoryTreeNode}
                      nodePath={historyTreeFocusPath ?? []}
                      selectedId={selectedId}
                      onSelect={(node) => void selectDocument(node.id)}
                      onOpenSubtree={openHistorySubtree}
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
              {treeFocusPath !== null && treeBreadcrumbPath.length > 0 ? (
                <DocumentTreeBreadcrumbs
                  path={treeBreadcrumbPath}
                  focusPath={treeFocusPath}
                  onNavigate={navigateTreeSubtree}
                />
              ) : null}
            </div>
            <div className="tree-toolbar-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={busyProjectId === "workspace"}
                onClick={() => void refresh(activeProject, true)}
              >
                {busyProjectId === "workspace"
                  ? "正在刷新…"
                  : "刷新工作空间映射"}
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
                    node={focusedTreeNode ?? tree}
                    nodePath={treeFocusPath ?? []}
                    selectedId={selectedId}
                    onSelect={(node) => void selectDocument(node.id)}
                    onOpenSubtree={openTreeSubtree}
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
});
