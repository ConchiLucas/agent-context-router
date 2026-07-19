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
import {
  createProject,
  getDocumentDetail,
  getProjectTree,
  listProjects,
  refreshProject,
} from "@/lib/api";
import type {
  DocumentDetail,
  DocumentTreeNode,
  ProjectSummary,
} from "@/lib/types";

function formattedTime(value: string | null): string {
  if (!value) return "尚未刷新";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function ProjectDashboard() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProject, setActiveProject] = useState<ProjectSummary | null>(null);
  const [tree, setTree] = useState<DocumentTreeNode | null>(null);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [agentsPath, setAgentsPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [draggingTree, setDraggingTree] = useState(false);
  const [busyProjectId, setBusyProjectId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const treeViewportRef = useRef<HTMLDivElement>(null);
  const treeDragRef = useRef<{
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

  async function selectDocument(node: DocumentTreeNode) {
    if (!activeProject) return;
    setSelectedId(node.id);
    setDetail(null);
    setDetailLoading(true);
    try {
      setDetail(await getDocumentDetail(activeProject.id, node.id));
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

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">AGENTS.md DOCUMENT MAP</p>
          <h1>文档索引项目</h1>
          <p className="page-intro">
            从每个项目的 AGENTS.md 开始，手动刷新并查看完整递归文档树。
          </p>
        </div>
        <button
          type="button"
          className="primary-button"
          onClick={() => setShowCreate((visible) => !visible)}
        >
          {showCreate ? "取消添加" : "添加项目"}
        </button>
      </header>

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
          <article className="project-card" key={project.id}>
            <div className="project-card-heading">
              <div>
                <span className="file-chip">AGENTS.md</span>
                <h2>{project.name}</h2>
              </div>
              <span className="node-count">{project.node_count} 个节点</span>
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
                onClick={() => void refresh(project)}
              >
                刷新映射
              </button>
              <button
                type="button"
                className="primary-button"
                disabled={busyProjectId === project.id}
                onClick={() => void loadTree(project)}
              >
                {busyProjectId === project.id ? "正在读取…" : "查看文档树"}
              </button>
            </div>
          </article>
        ))}
      </section>

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
                    onSelect={(node) => void selectDocument(node)}
                  />
                </ul>
              </div>
            </div>
          </section>

          {selectedId ? (
            <aside
              className="document-detail-drawer"
              role="dialog"
              aria-label="Markdown 文档详情"
            >
              <button
                type="button"
                className="close-button detail-close-button"
                aria-label="关闭文档详情"
                onClick={closeDetail}
              >
                ×
              </button>
              {detailLoading ? (
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
          ) : null}
        </div>
      ) : null}
    </>
  );
}
