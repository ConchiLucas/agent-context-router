"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";

import {
  getWorkspaceContainerLogStreamUrl,
  listWorkspaceContainers,
  runWorkspaceContainerBulkAction,
} from "@/lib/api";
import {
  executeProjectRuntimeConfig,
  getWorkspaceHostRuntimeStatus,
  getWorkspaceRuntimeOperation,
  getWorkspaceRuntimeRunnerStatus,
  startAndCheckWorkspace,
  type RuntimeMode,
  type RuntimeOperationSummary,
  type RuntimeOperationStatus,
} from "@/lib/runtime-api";
import type {
  WorkspaceContainer,
  WorkspaceContainerBulkAction,
  WorkspaceContainerBulkActionResult,
  WorkspaceSummary,
} from "@/lib/types";

interface WorkspaceContainersModalProps {
  workspace: WorkspaceSummary;
}

type ContainerTab = "backend" | "frontend";
type LogConnectionState =
  | "connecting"
  | "live"
  | "reconnecting"
  | "ended"
  | "error";

interface ContainerLogLine {
  key: number;
  stream: "stdout" | "stderr" | "system";
  content: string;
  timestamp: string | null;
}

interface ProjectUpdateState {
  mode: RuntimeMode;
  status: RuntimeOperationStatus | "submitting";
  operationId: string | null;
  projectName: string;
  message: string;
}

type ReadinessStatus = "pending" | "ready" | "failed";

interface WorkspaceReadiness {
  infrastructure: WorkspaceReadinessLevel;
  services: WorkspaceReadinessLevel;
  business: WorkspaceReadinessLevel;
  revision: string | null;
}

interface WorkspaceReadinessLevel {
  status: ReadinessStatus;
  durationMs: number | null;
  errorMessage: string | null;
}

interface WorkspaceStartState {
  status: RuntimeOperationStatus | "submitting";
  operationId: string | null;
  message: string;
  readiness: WorkspaceReadiness;
}

const MAX_LOG_LINES = 2000;
const ACTIVE_UPDATE_STATUSES = new Set<ProjectUpdateState["status"]>([
  "submitting",
  "queued",
  "leased",
  "running",
]);
const CONTAINER_TABS: Array<{ key: ContainerTab; label: string }> = [
  { key: "backend", label: "后端" },
  { key: "frontend", label: "前端" },
];
const EMPTY_READINESS: WorkspaceReadiness = {
  infrastructure: { status: "pending", durationMs: null, errorMessage: null },
  services: { status: "pending", durationMs: null, errorMessage: null },
  business: { status: "pending", durationMs: null, errorMessage: null },
  revision: null,
};
const READINESS_ITEMS: Array<{
  key: keyof Pick<WorkspaceReadiness, "infrastructure" | "services" | "business">;
  label: string;
  description: string;
}> = [
  { key: "infrastructure", label: "基础设施", description: "网络、中间件、数据库代理与网关" },
  { key: "services", label: "项目服务", description: "已注册的后端与前端容器" },
  { key: "business", label: "业务入口", description: "登录页与登录密钥接口" },
];

const STATE_LABELS: Record<string, string> = {
  created: "已创建",
  dead: "异常",
  exited: "已停止",
  paused: "已暂停",
  removing: "删除中",
  restarting: "重启中",
  running: "运行中",
};

const HEALTH_LABELS: Record<string, string> = {
  healthy: "健康",
  starting: "检查中",
  unhealthy: "不健康",
};

const LOG_STATE_LABELS: Record<LogConnectionState, string> = {
  connecting: "连接中",
  live: "实时",
  reconnecting: "正在重连",
  ended: "已结束",
  error: "连接失败",
};

function logTime(timestamp: string | null): string {
  if (!timestamp) return "--:--:--";
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime())
    ? timestamp
    : parsed.toLocaleTimeString("zh-CN", { hour12: false });
}

function updateButtonLabel(
  mode: RuntimeMode,
  state: ProjectUpdateState | undefined,
): string {
  const prefix = mode === "fast" ? "Fast" : "Full";
  if (!state || state.mode !== mode) return `${prefix}更新`;
  if (state.status === "submitting") return `${prefix}提交中`;
  if (state.status === "queued") return `${prefix}排队中`;
  if (state.status === "leased") return `${prefix}已领取`;
  if (state.status === "running") return `${prefix}执行中`;
  if (state.status === "succeeded") return `${prefix}成功`;
  if (state.status === "cancelled") return `${prefix}已取消`;
  if (state.status === "interrupted") return `${prefix}已中断`;
  return `${prefix}失败`;
}

function operationMessage(
  status: RuntimeOperationStatus,
  errorMessage: string | null,
  stepErrorMessage: string | null,
  log: string,
): string {
  if (status === "succeeded") return "更新完成";
  if (status === "cancelled") return "更新已取消";
  if (status === "interrupted") return "Host Runtime Runner 执行中断";
  if (status === "failed") {
    const summary = stepErrorMessage || errorMessage;
    const tail = log
      .trim()
      .split("\n")
      .filter(Boolean)
      .slice(-3)
      .join(" ")
      .slice(-500);
    if (summary && tail && !tail.includes(summary)) {
      return `${summary}；${tail}`;
    }
    return summary || tail || "更新执行失败，请检查运行日志";
  }
  if (errorMessage) return errorMessage;
  if (stepErrorMessage) return stepErrorMessage;
  return status === "queued" ? "更新任务正在排队" : "更新任务执行中";
}

function parseReadiness(operation: RuntimeOperationSummary): WorkspaceReadiness {
  const structured = operation.steps
    .map((step) => step.readiness)
    .find((item) => item !== null);
  if (structured) {
    return {
      infrastructure: {
        status: structured.infrastructure.status,
        durationMs: structured.infrastructure.duration_ms,
        errorMessage: structured.infrastructure.error_message,
      },
      services: {
        status: structured.services.status,
        durationMs: structured.services.duration_ms,
        errorMessage: structured.services.error_message,
      },
      business: {
        status: structured.business.status,
        durationMs: structured.business.duration_ms,
        errorMessage: structured.business.error_message,
      },
      revision: structured.revision?.toString() ?? null,
    };
  }
  const log = operation.steps.map((step) => step.log).join("\n");
  const matches = [...log.matchAll(
    /\[READINESS\]\s+infrastructure=(pending|ready|failed)\s+services=(pending|ready|failed)\s+business=(pending|ready|failed)(?:\s+revision=([^\s]+))?/g,
  )];
  const latest = matches.at(-1);
  if (latest) {
    return {
      infrastructure: {
        status: latest[1] as ReadinessStatus,
        durationMs: null,
        errorMessage: null,
      },
      services: {
        status: latest[2] as ReadinessStatus,
        durationMs: null,
        errorMessage: null,
      },
      business: {
        status: latest[3] as ReadinessStatus,
        durationMs: null,
        errorMessage: null,
      },
      revision: latest[4] && latest[4] !== "unknown" ? latest[4] : null,
    };
  }
  if (operation.status === "succeeded") {
    return {
      infrastructure: { status: "ready", durationMs: null, errorMessage: null },
      services: { status: "ready", durationMs: null, errorMessage: null },
      business: { status: "ready", durationMs: null, errorMessage: null },
      revision: null,
    };
  }
  if (["failed", "cancelled", "interrupted"].includes(operation.status)) {
    return {
      infrastructure: { status: "failed", durationMs: null, errorMessage: null },
      services: { status: "failed", durationMs: null, errorMessage: null },
      business: { status: "failed", durationMs: null, errorMessage: null },
      revision: null,
    };
  }
  return EMPTY_READINESS;
}

function workspaceStartMessage(operation: RuntimeOperationSummary): string {
  const step = operation.steps[0];
  if (operation.status === "succeeded") return "工作空间已启动，三级验收全部通过";
  if (operation.status === "failed") {
    return operationMessage(
      operation.status,
      operation.error_message,
      step?.error_message ?? null,
      step?.log ?? "",
    );
  }
  if (operation.status === "cancelled") return "启动与检查已取消";
  if (operation.status === "interrupted") return "启动与检查被中断";
  return operation.status === "queued"
    ? "启动与检查任务正在排队"
    : "正在保障基础设施、恢复项目服务并执行验收";
}

export function WorkspaceContainersModal({
  workspace,
}: WorkspaceContainersModalProps) {
  const [open, setOpen] = useState(false);
  const [containers, setContainers] = useState<WorkspaceContainer[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedTab, setSelectedTab] = useState<ContainerTab>("backend");
  const [activeContainer, setActiveContainer] =
    useState<WorkspaceContainer | null>(null);
  const [logLines, setLogLines] = useState<ContainerLogLine[]>([]);
  const [logState, setLogState] =
    useState<LogConnectionState>("connecting");
  const [autoScroll, setAutoScroll] = useState(true);
  const [pendingBulkAction, setPendingBulkAction] =
    useState<WorkspaceContainerBulkAction | null>(null);
  const [bulkActionBusy, setBulkActionBusy] = useState(false);
  const [bulkActionResult, setBulkActionResult] =
    useState<WorkspaceContainerBulkActionResult | null>(null);
  const [bulkActionError, setBulkActionError] = useState("");
  const [projectUpdates, setProjectUpdates] = useState<
    Record<string, ProjectUpdateState>
  >({});
  const [runnerAvailable, setRunnerAvailable] = useState<boolean | null>(null);
  const [runnerStatusError, setRunnerStatusError] = useState("");
  const [workspaceStart, setWorkspaceStart] = useState<WorkspaceStartState | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const logEndRef = useRef<HTMLDivElement>(null);
  const logKeyRef = useRef(0);
  const seenLogIdsRef = useRef(new Set<string>());
  const titleId = useId();

  const workspaceStartBusy = workspaceStart
    ? workspaceStart.status === "submitting" ||
      ACTIVE_UPDATE_STATUSES.has(workspaceStart.status)
    : false;

  const loadContainers = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setContainers(await listWorkspaceContainers(workspace.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "容器列表读取失败");
    } finally {
      setLoading(false);
    }
  }, [workspace.id]);

  const loadRunnerStatus = useCallback(async () => {
    setRunnerStatusError("");
    try {
      const result = await getWorkspaceRuntimeRunnerStatus(workspace.id);
      setRunnerAvailable(result.available);
    } catch (caught) {
      setRunnerAvailable(false);
      setRunnerStatusError(
        caught instanceof Error ? caught.message : "Host Runtime Runner 状态读取失败",
      );
    }
  }, [workspace.id]);

  const loadLatestWorkspaceStart = useCallback(async () => {
    try {
      const result = await getWorkspaceHostRuntimeStatus(workspace.id);
      setRunnerAvailable(result.runner_available);
      const latest = result.latest_operation;
      if (latest?.action !== "pzh.start-and-check") return;
      const operation = await getWorkspaceRuntimeOperation(workspace.id, latest.id);
      setWorkspaceStart({
        status: operation.status,
        operationId: operation.id,
        message: workspaceStartMessage(operation),
        readiness: parseReadiness(operation),
      });
    } catch {
      // Runner availability already has its own visible error handling.
    }
  }, [workspace.id]);

  const close = useCallback(() => {
    if (bulkActionBusy) return;
    setActiveContainer(null);
    setPendingBulkAction(null);
    setBulkActionResult(null);
    setBulkActionError("");
    setOpen(false);
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  }, [bulkActionBusy]);

  const selectTab = useCallback((tab: ContainerTab) => {
    if (bulkActionBusy) return;
    setActiveContainer(null);
    setPendingBulkAction(null);
    setBulkActionResult(null);
    setBulkActionError("");
    setSelectedTab(tab);
  }, [bulkActionBusy]);

  const openLogs = useCallback((container: WorkspaceContainer) => {
    setLogLines([]);
    setLogState("connecting");
    setAutoScroll(true);
    setActiveContainer(container);
  }, []);

  const appendSystemLine = useCallback((content: string) => {
    setLogLines((current) => [
      ...current.slice(-(MAX_LOG_LINES - 1)),
      {
        key: ++logKeyRef.current,
        stream: "system",
        content,
        timestamp: null,
      },
    ]);
  }, []);

  const visibleContainers = containers.filter(
    (container) => (container.project_kind ?? "backend") === selectedTab,
  );
  const selectedTabLabel = selectedTab === "backend" ? "后端" : "前端";
  const activeUpdateOperationKey = Object.entries(projectUpdates)
    .filter(
      ([, state]) =>
        state.operationId !== null && ACTIVE_UPDATE_STATUSES.has(state.status),
    )
    .map(([projectId, state]) => `${projectId}:${state.operationId}`)
    .sort()
    .join("|");
  const completedUpdateFeedback = Object.entries(projectUpdates).filter(
    ([, state]) =>
      state.status !== "submitting" && !ACTIVE_UPDATE_STATUSES.has(state.status),
  );

  async function runProjectUpdate(
    container: WorkspaceContainer,
    mode: RuntimeMode,
  ) {
    const projectId = container.project_id;
    const currentUpdate = projectId ? projectUpdates[projectId] : undefined;
    if (
      !projectId ||
      runnerAvailable !== true ||
      workspaceStartBusy ||
      (currentUpdate && ACTIVE_UPDATE_STATUSES.has(currentUpdate.status))
    ) {
      return;
    }
    setProjectUpdates((current) => ({
      ...current,
      [projectId]: {
        mode,
        status: "submitting",
        operationId: null,
        projectName: container.project_name ?? container.name,
        message: `${container.name} 正在提交${mode === "fast" ? "快速" : "完整"}更新`,
      },
    }));
    try {
      const operation = await executeProjectRuntimeConfig(projectId, mode);
      setProjectUpdates((current) => ({
        ...current,
        [projectId]: {
          mode,
          status: operation.status,
          operationId: operation.id,
          projectName: container.project_name ?? container.name,
          message: operation.error_message ?? "更新任务已提交给 Host Runtime Runner",
        },
      }));
    } catch (caught) {
      setProjectUpdates((current) => ({
        ...current,
        [projectId]: {
          mode,
          status: "failed",
          operationId: null,
          projectName: container.project_name ?? container.name,
          message: caught instanceof Error ? caught.message : "更新任务提交失败",
        },
      }));
    }
  }

  async function runBulkAction() {
    if (!pendingBulkAction || bulkActionBusy || workspaceStartBusy) return;
    const action = pendingBulkAction;
    setBulkActionBusy(true);
    setBulkActionError("");
    setBulkActionResult(null);
    setActiveContainer(null);
    try {
      const result = await runWorkspaceContainerBulkAction(
        workspace.id,
        action,
        selectedTab,
      );
      setBulkActionResult(result);
      setPendingBulkAction(null);
      await loadContainers();
    } catch (caught) {
      setBulkActionError(
        caught instanceof Error ? caught.message : "容器批量操作失败",
      );
    } finally {
      setBulkActionBusy(false);
    }
  }

  async function runWorkspaceStartAndCheck() {
    if (workspaceStartBusy || runnerAvailable !== true) return;
    setActiveContainer(null);
    setPendingBulkAction(null);
    setBulkActionResult(null);
    setBulkActionError("");
    setWorkspaceStart({
      status: "submitting",
      operationId: null,
      message: "正在提交启动与检查任务",
      readiness: EMPTY_READINESS,
    });
    try {
      const operation = await startAndCheckWorkspace(workspace.id);
      setWorkspaceStart({
        status: operation.status,
        operationId: operation.id,
        message: workspaceStartMessage(operation),
        readiness: parseReadiness(operation),
      });
    } catch (caught) {
      setWorkspaceStart({
        status: "failed",
        operationId: null,
        message: caught instanceof Error ? caught.message : "启动与检查任务提交失败",
        readiness: {
          infrastructure: { status: "failed", durationMs: null, errorMessage: null },
          services: { status: "failed", durationMs: null, errorMessage: null },
          business: { status: "failed", durationMs: null, errorMessage: null },
          revision: null,
        },
      });
    }
  }

  useEffect(() => {
    if (!open) return;
    void loadContainers();
    void loadRunnerStatus();
    void loadLatestWorkspaceStart();
    const timer = window.setInterval(() => void loadRunnerStatus(), 10000);
    return () => window.clearInterval(timer);
  }, [open, loadContainers, loadLatestWorkspaceStart, loadRunnerStatus]);

  useEffect(() => {
    const operationId = workspaceStart?.operationId;
    if (!open || !operationId || !workspaceStartBusy) return;
    const activeOperationId = operationId;
    let cancelled = false;

    async function pollWorkspaceStart() {
      try {
        const operation = await getWorkspaceRuntimeOperation(workspace.id, activeOperationId);
        if (cancelled) return;
        setWorkspaceStart({
          status: operation.status,
          operationId: operation.id,
          message: workspaceStartMessage(operation),
          readiness: parseReadiness(operation),
        });
        if (operation.status === "succeeded") void loadContainers();
      } catch (caught) {
        if (cancelled) return;
        setWorkspaceStart((current) => current ? {
          ...current,
          message: caught instanceof Error ? caught.message : "启动状态读取失败",
        } : current);
      }
    }

    void pollWorkspaceStart();
    const timer = window.setInterval(() => void pollWorkspaceStart(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [loadContainers, open, workspace.id, workspaceStart?.operationId, workspaceStartBusy]);

  useEffect(() => {
    if (!open || !activeUpdateOperationKey) return;
    const targets = activeUpdateOperationKey.split("|").map((item) => {
      const separator = item.lastIndexOf(":");
      return {
        projectId: item.slice(0, separator),
        operationId: item.slice(separator + 1),
      };
    });
    let cancelled = false;

    async function pollOperations() {
      const results = await Promise.allSettled(
        targets.map(({ operationId }) =>
          getWorkspaceRuntimeOperation(workspace.id, operationId),
        ),
      );
      if (cancelled) return;
      setProjectUpdates((current) => {
        const next = { ...current };
        results.forEach((result, index) => {
          if (result.status !== "fulfilled") return;
          const operation = result.value;
          const projectId = targets[index].projectId;
          const previous = current[projectId];
          const step = operation.steps.find(
            (item) => item.owner_type === "project" && item.owner_id === projectId,
          ) ?? operation.steps[0];
          next[projectId] = {
            mode: step?.mode === "full" ? "full" : "fast",
            status: operation.status,
            operationId: operation.id,
            projectName: previous?.projectName ?? projectId,
            message: operationMessage(
              operation.status,
              operation.error_message,
              step?.error_message ?? null,
              step?.log ?? "",
            ),
          };
        });
        return next;
      });
      if (
        results.some(
          (result) =>
            result.status === "fulfilled" && result.value.status === "succeeded",
        )
      ) {
        void loadContainers();
      }
    }

    void pollOperations();
    const timer = window.setInterval(() => void pollOperations(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeUpdateOperationKey, loadContainers, open, workspace.id]);

  useEffect(() => {
    if (!open || !activeContainer) return;

    seenLogIdsRef.current.clear();
    const eventSource = new EventSource(
      getWorkspaceContainerLogStreamUrl(workspace.id, activeContainer.id),
    );

    eventSource.addEventListener("ready", () => setLogState("live"));
    eventSource.addEventListener("log", (rawEvent) => {
      const event = rawEvent as MessageEvent<string>;
      try {
        const payload = JSON.parse(event.data) as {
          stream?: string;
          content?: string;
          timestamp?: string | null;
        };
        const stream: "stdout" | "stderr" =
          payload.stream === "stderr" ? "stderr" : "stdout";
        const identity = `${event.lastEventId}|${stream}|${payload.content ?? ""}`;
        if (seenLogIdsRef.current.has(identity)) return;
        seenLogIdsRef.current.add(identity);
        setLogLines((current) => [
          ...current,
          {
            key: ++logKeyRef.current,
            stream,
            content: payload.content ?? "",
            timestamp: payload.timestamp ?? null,
          },
        ].slice(-MAX_LOG_LINES));
      } catch {
        appendSystemLine("收到无法解析的日志事件");
      }
    });
    eventSource.addEventListener("stream-error", (rawEvent) => {
      setLogState("error");
      const event = rawEvent as MessageEvent<string>;
      try {
        const payload = JSON.parse(event.data) as { message?: string };
        appendSystemLine(payload.message ?? "实时日志连接中断");
      } catch {
        appendSystemLine("实时日志连接中断");
      }
    });
    eventSource.addEventListener("end", () => {
      setLogState("ended");
      eventSource.close();
    });
    eventSource.onerror = () => {
      setLogState(
        eventSource.readyState === EventSource.CLOSED ? "error" : "reconnecting",
      );
    };

    return () => eventSource.close();
  }, [activeContainer, appendSystemLine, open, workspace.id]);

  useEffect(() => {
    if (autoScroll) logEndRef.current?.scrollIntoView({ block: "end" });
  }, [autoScroll, logLines]);

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    const focusable = dialog?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    focusable?.[0]?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (event.key !== "Tab" || !focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [close, open]);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="secondary-button workspace-containers-button"
        onClick={() => {
          setSelectedTab("backend");
          setPendingBulkAction(null);
          setBulkActionResult(null);
          setBulkActionError("");
          setProjectUpdates({});
          setRunnerAvailable(null);
          setRunnerStatusError("");
          setWorkspaceStart(null);
          setOpen(true);
        }}
      >
        查看容器
      </button>
      {open ? (
        <div
          className="project-settings-modal workspace-containers-overlay"
          role="presentation"
        >
          <section
            ref={dialogRef}
            className="management-modal workspace-containers-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
          >
            <header>
              <div>
                <span className="file-chip">Docker</span>
                <h2 id={titleId}>{workspace.name} 的容器</h2>
              </div>
              <button
                type="button"
                className="close-button"
                aria-label="关闭容器列表"
                disabled={bulkActionBusy}
                onClick={close}
              >
                ×
              </button>
            </header>

            <nav
              className="workspace-container-tabs"
              role="tablist"
              aria-label="容器项目类型"
            >
              {CONTAINER_TABS.map((tab) => {
                const count = containers.filter(
                  (container) =>
                    (container.project_kind ?? "backend") === tab.key,
                ).length;
                return (
                  <button
                    key={tab.key}
                    type="button"
                    role="tab"
                    aria-selected={selectedTab === tab.key}
                    data-active={selectedTab === tab.key}
                    disabled={bulkActionBusy}
                    onClick={() => selectTab(tab.key)}
                  >
                    <span>{tab.label}</span>
                    <small>{count}</small>
                  </button>
                );
              })}
            </nav>

            {runnerAvailable === null ? (
              <p className="workspace-runtime-runner-status" role="status">
                正在检查 Host Runtime Runner…
              </p>
            ) : null}
            {runnerAvailable === false ? (
              <div className="error-banner workspace-runtime-runner-status" role="alert">
                {runnerStatusError ||
                  "Host Runtime Runner 当前不在线，请先启动本机 Context Router 托管脚本。"}
              </div>
            ) : null}

            <section className="workspace-readiness-panel" aria-label="工作空间运行状态">
              <div className="workspace-readiness-heading">
                <div>
                  <strong>工作空间运行状态</strong>
                  <span>
                    一次完成基础设施保障、缺失项目 Fast 部署和业务验收
                  </span>
                </div>
                <button
                  type="button"
                  className="primary-button"
                  disabled={
                    runnerAvailable !== true ||
                    workspaceStartBusy ||
                    bulkActionBusy ||
                    Object.values(projectUpdates).some((state) =>
                      ACTIVE_UPDATE_STATUSES.has(state.status),
                    )
                  }
                  onClick={() => void runWorkspaceStartAndCheck()}
                >
                  {workspaceStartBusy ? "启动并检查中…" : "启动并检查"}
                </button>
              </div>
              <div className="workspace-readiness-levels">
                {READINESS_ITEMS.map((item) => {
                  const level = workspaceStart?.readiness[item.key] ??
                    EMPTY_READINESS[item.key];
                  const status = level.status;
                  return (
                    <div key={item.key} data-status={status}>
                      <span aria-hidden="true" />
                      <div>
                        <strong>{item.label}</strong>
                        <small>
                          {level.errorMessage ?? item.description}
                          {level.durationMs !== null
                            ? ` · ${(level.durationMs / 1000).toFixed(1)} 秒`
                            : ""}
                        </small>
                      </div>
                      <b>
                        {status === "ready"
                          ? "就绪"
                          : status === "failed"
                            ? "异常"
                            : "待检查"}
                      </b>
                    </div>
                  );
                })}
              </div>
              {workspaceStart ? (
                <p
                  className="workspace-readiness-message"
                  data-status={workspaceStart.status}
                  role={workspaceStart.status === "failed" ? "alert" : "status"}
                >
                  {workspaceStart.message}
                  {workspaceStart.readiness.revision
                    ? ` · 脚本版本 r${workspaceStart.readiness.revision}`
                    : ""}
                  {workspaceStart.operationId
                    ? ` · 运行 ${workspaceStart.operationId.slice(0, 8)}`
                    : ""}
                </p>
              ) : (
                <p className="workspace-readiness-message" role="status">
                  尚未执行本次会话的运行验收
                </p>
              )}
            </section>

            <div className="workspace-containers-content">
              {loading ? (
                <p className="workspace-containers-message" role="status">
                  正在读取容器…
                </p>
              ) : null}
              {!loading && error ? (
                <div className="workspace-containers-error">
                  <div className="error-banner" role="alert">
                    {error}
                  </div>
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => void loadContainers()}
                  >
                    重试
                  </button>
                </div>
              ) : null}
              {!loading && !error && containers.length === 0 ? (
                <div className="workspace-containers-empty">
                  <strong>当前没有已关联的容器</strong>
                  <p>容器在下次受控部署后会按工作空间标签自动显示在这里。</p>
                </div>
              ) : null}
              {!loading && !error && containers.length > 0 ? (
                <div className="workspace-container-table" aria-live="polite">
                  <div className="workspace-container-table-head" aria-hidden="true">
                    <span>容器 / 项目</span>
                    <span>镜像</span>
                    <span>状态</span>
                    <span>端口</span>
                    <span>操作</span>
                  </div>
                  <div className="workspace-container-list">
                    {visibleContainers.map((container) => {
                      const updateState = container.project_id
                        ? projectUpdates[container.project_id]
                        : undefined;
                      const updateBusy = updateState
                        ? ACTIVE_UPDATE_STATUSES.has(updateState.status)
                        : false;
                      return (
                        <article
                        className="workspace-container-row"
                        data-active={activeContainer?.id === container.id}
                        key={container.id}
                      >
                        <div className="workspace-container-identity">
                          <strong>{container.name}</strong>
                          <span>
                            {container.project_name ??
                              container.project_id ??
                              "未关联项目"}
                          </span>
                          <small>
                            {container.mode
                              ? `${container.mode === "fast" ? "Fast" : "Full"} 模式`
                              : "部署模式未知"}
                            {container.operation_id
                              ? ` · 运行 ${container.operation_id.slice(0, 8)}`
                              : ""}
                          </small>
                        </div>
                        <code className="workspace-container-image">
                          {container.image}
                        </code>
                        <div className="workspace-container-state">
                          <div className="workspace-container-statuses">
                            <span data-state={container.state}>
                              {STATE_LABELS[container.state] ?? container.state}
                            </span>
                            {container.health ? (
                              <span data-health={container.health}>
                                {HEALTH_LABELS[container.health] ?? container.health}
                              </span>
                            ) : null}
                          </div>
                          <small>{container.status}</small>
                        </div>
                        <div className="workspace-container-ports">
                          {container.ports.length > 0 ? (
                            container.ports.map((port) => (
                              <code key={port}>{port}</code>
                            ))
                          ) : (
                            <span>未暴露端口</span>
                          )}
                        </div>
                          <div className="workspace-container-actions">
                            <button
                              type="button"
                              className="workspace-container-log-button"
                              aria-pressed={activeContainer?.id === container.id}
                              disabled={bulkActionBusy || updateBusy}
                              onClick={() => openLogs(container)}
                            >
                              日志
                            </button>
                            {(["fast", "full"] as RuntimeMode[]).map((mode) => (
                              <button
                                key={mode}
                                type="button"
                                className="workspace-container-update-button"
                                data-mode={mode}
                                data-status={
                                  updateState?.mode === mode
                                    ? updateState.status
                                    : undefined
                                }
                                disabled={
                                  bulkActionBusy ||
                                  workspaceStartBusy ||
                                  updateBusy ||
                                  !container.project_id ||
                                  runnerAvailable !== true
                                }
                                title={
                                  !container.project_id
                                    ? "容器未关联项目，无法更新"
                                    : runnerAvailable !== true
                                      ? "Host Runtime Runner 当前不可用"
                                    : updateState?.mode === mode
                                      ? updateState.message
                                      : `${mode === "fast" ? "快速" : "完整"}更新 ${container.project_name ?? container.name}`
                                }
                                onClick={() => void runProjectUpdate(container, mode)}
                              >
                                {updateButtonLabel(mode, updateState)}
                              </button>
                            ))}
                          </div>
                        </article>
                      );
                    })}
                    {visibleContainers.length === 0 ? (
                      <p className="workspace-container-tab-empty">
                        当前没有{selectedTab === "backend" ? "后端" : "前端"}容器
                      </p>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>

            {completedUpdateFeedback.length > 0 ? (
              <div className="workspace-container-update-feedback" aria-live="polite">
                {completedUpdateFeedback.map(([projectId, state]) => (
                  <div
                    key={`${projectId}:${state.operationId ?? state.mode}`}
                    className={
                      state.status === "succeeded" ? "success-banner" : "error-banner"
                    }
                    role={state.status === "succeeded" ? "status" : "alert"}
                  >
                    {state.projectName} · {state.mode === "fast" ? "Fast" : "Full"}
                    更新{state.status === "succeeded" ? "成功" : "失败"}：{state.message}
                  </div>
                ))}
              </div>
            ) : null}

            {activeContainer ? (
              <section
                className="workspace-container-log-panel"
                aria-label={`${activeContainer.name} 实时日志`}
              >
                <header>
                  <div className="workspace-container-log-title">
                    <strong>{activeContainer.name}</strong>
                    <span data-state={logState}>{LOG_STATE_LABELS[logState]}</span>
                  </div>
                  <div className="workspace-container-log-actions">
                    <label>
                      <input
                        type="checkbox"
                        checked={autoScroll}
                        onChange={(event) => setAutoScroll(event.target.checked)}
                      />
                      自动滚动
                    </label>
                    <button type="button" onClick={() => setLogLines([])}>
                      清空
                    </button>
                    <button
                      type="button"
                      aria-label="收起实时日志"
                      onClick={() => setActiveContainer(null)}
                    >
                      ×
                    </button>
                  </div>
                </header>
                <div className="workspace-container-log-output" role="log">
                  {logLines.length === 0 ? (
                    <p>{logState === "live" ? "等待新日志…" : "正在连接日志流…"}</p>
                  ) : null}
                  {logLines.map((line) => (
                    <div key={line.key} data-stream={line.stream}>
                      <time>{logTime(line.timestamp)}</time>
                      <span>
                        {line.stream === "stderr"
                          ? "ERR"
                          : line.stream === "system"
                            ? "SYS"
                            : "OUT"}
                      </span>
                      <code>{line.content || " "}</code>
                    </div>
                  ))}
                  <div ref={logEndRef} />
                </div>
              </section>
            ) : null}

            {pendingBulkAction || bulkActionResult || bulkActionError ? (
              <div className="workspace-container-bulk-feedback">
                {pendingBulkAction ? (
                  <div className="workspace-container-bulk-confirm" role="alert">
                    <div>
                      <strong>
                        确认{pendingBulkAction === "restart" ? "重启" : "停止"}
                        全部{selectedTabLabel}容器？
                      </strong>
                      <span>
                        当前列表中有 {visibleContainers.length} 个{selectedTabLabel}
                        容器，操作不会影响另一个 Tab。
                      </span>
                    </div>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={bulkActionBusy}
                      onClick={() => setPendingBulkAction(null)}
                    >
                      取消
                    </button>
                    <button
                      type="button"
                      className={
                        pendingBulkAction === "stop"
                          ? "danger-button"
                          : "primary-button"
                      }
                      disabled={bulkActionBusy}
                      onClick={() => void runBulkAction()}
                    >
                      {bulkActionBusy
                        ? "执行中…"
                        : `确认${pendingBulkAction === "restart" ? "重启" : "停止"}`}
                    </button>
                  </div>
                ) : null}
                {bulkActionResult ? (
                  <div
                    className={
                      bulkActionResult.failed_count > 0
                        ? "error-banner"
                        : "success-banner"
                    }
                    role="status"
                  >
                    {selectedTabLabel}容器
                    {bulkActionResult.action === "restart" ? "重启" : "停止"}
                    完成：成功 {bulkActionResult.succeeded_count} 个，失败 {bulkActionResult.failed_count} 个。
                    {bulkActionResult.failed_containers.length > 0
                      ? ` ${bulkActionResult.failed_containers.join("；")}`
                      : ""}
                  </div>
                ) : null}
                {bulkActionError ? (
                  <div className="error-banner" role="alert">
                    {bulkActionError}
                  </div>
                ) : null}
              </div>
            ) : null}

            <footer>
              <div className="workspace-container-footer-actions">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={loading || bulkActionBusy}
                  onClick={() => void loadContainers()}
                >
                  {loading ? "刷新中…" : "刷新列表"}
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={
                    bulkActionBusy || workspaceStartBusy || visibleContainers.length === 0
                  }
                  onClick={() => {
                    setPendingBulkAction("restart");
                    setBulkActionResult(null);
                    setBulkActionError("");
                  }}
                >
                  重启全部{selectedTabLabel}
                </button>
                <button
                  type="button"
                  className="danger-button"
                  disabled={
                    bulkActionBusy || workspaceStartBusy || visibleContainers.length === 0
                  }
                  onClick={() => {
                    setPendingBulkAction("stop");
                    setBulkActionResult(null);
                    setBulkActionError("");
                  }}
                >
                  停止全部{selectedTabLabel}
                </button>
              </div>
              <button
                type="button"
                className="primary-button"
                disabled={bulkActionBusy}
                onClick={close}
              >
                关闭
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}
