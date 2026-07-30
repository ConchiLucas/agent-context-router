"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getWorkspaceDatabaseEnvironmentMappings,
  getWorkspaceEnvironmentConfig,
  replaceWorkspaceDatabaseEnvironmentMappings,
  replaceWorkspaceEnvironmentConfig,
  setWorkspaceDatabaseEnvironment,
} from "@/lib/api";
import {
  ENVIRONMENT_JSON_TOTAL_MAX_BYTES,
  environmentJsonByteLength,
  formatEnvironmentJson,
  parseEnvironmentJson,
} from "@/lib/environment-config";
import type {
  DatabaseEnvironment,
  DatabaseEnvironmentTarget,
  WorkspaceDatabaseEnvironmentMapping,
  WorkspaceDatabaseEnvironmentMappings,
  WorkspaceEnvironmentConfig,
  WorkspaceSummary,
} from "@/lib/types";

const ENVIRONMENTS: DatabaseEnvironment[] = ["test", "uat"];
type EnvironmentPanelTab = "database-mappings" | "environment-json";

const ENVIRONMENT_LABELS: Record<DatabaseEnvironment, string> = {
  test: "TEST",
  uat: "UAT",
};

const MCP_ALIAS_PATTERN = /^[a-z][a-z0-9_-]{0,63}$/;

const ISSUE_LABELS: Record<string, string> = {
  alias_conflict: "MCP 别名重复",
  ambiguous_match: "存在多个同后缀候选",
  database_unavailable: "数据库不可用",
  engine_mismatch: "TEST/UAT 数据库类型不同",
  namespace_mismatch: "TEST/UAT 命名空间类型不同",
  link_disabled: "项目数据库授权已停用",
  missing_mcp_alias: "缺少 MCP 别名",
  missing_test: "缺少 TEST 数据库",
  missing_uat: "缺少 UAT 数据库",
  source_disabled: "数据源已停用",
};

interface MappingDraft {
  key: string;
  id: string | null;
  projectId: string;
  projectName: string;
  logicalName: string;
  mcpAlias: string;
  testLinkId: string;
  uatLinkId: string;
  source: WorkspaceDatabaseEnvironmentMapping;
}

interface EvaluatedDraft {
  draft: MappingDraft;
  issues: string[];
}

interface WorkspaceEnvironmentMappingProps {
  workspace: WorkspaceSummary;
  onClose: () => void;
  onEnvironmentChanged?: (environment: DatabaseEnvironment | null) => void;
}

function environmentTarget(
  draft: MappingDraft,
  environment: DatabaseEnvironment,
  targetIndex: Map<string, DatabaseEnvironmentTarget>,
): DatabaseEnvironmentTarget | null {
  const linkId =
    environment === "test" ? draft.testLinkId : draft.uatLinkId;
  return linkId
    ? (targetIndex.get(`${draft.projectId}:${linkId}`) ?? null)
    : null;
}

function issueLabel(issue: string): string {
  return ISSUE_LABELS[issue] ?? issue.replaceAll("_", " ");
}

function buildDrafts(
  configuration: WorkspaceDatabaseEnvironmentMappings,
): MappingDraft[] {
  return configuration.projects
    .filter((project) => project.project_kind === "backend")
    .flatMap((project) =>
      project.mappings.map((mapping, index) => ({
        key:
          mapping.id ??
          `${project.project_id}:${mapping.logical_name || mapping.mcp_alias || index}`,
        id: mapping.id,
        projectId: project.project_id,
        projectName: project.project_name,
        logicalName: mapping.logical_name,
        mcpAlias: mapping.mcp_alias,
        testLinkId: mapping.targets.test?.link_id ?? "",
        uatLinkId: mapping.targets.uat?.link_id ?? "",
        source: mapping,
      })),
    );
}

function mappingChanged(draft: MappingDraft): boolean {
  return (
    draft.logicalName !== draft.source.logical_name ||
    draft.mcpAlias !== draft.source.mcp_alias ||
    draft.testLinkId !== (draft.source.targets.test?.link_id ?? "") ||
    draft.uatLinkId !== (draft.source.targets.uat?.link_id ?? "")
  );
}

function targetTitle(target: DatabaseEnvironmentTarget): string {
  return target.database_display_name || target.database_name;
}

function targetAvailable(target: DatabaseEnvironmentTarget): boolean {
  return Boolean(
    target.available &&
      target.source_enabled &&
      target.readonly &&
      target.link_enabled &&
      !target.system_database,
  );
}

function resolveActiveEnvironment(
  configuration: WorkspaceDatabaseEnvironmentMappings | null,
  environmentConfig: WorkspaceEnvironmentConfig | null,
): DatabaseEnvironment | null {
  if (configuration?.enabled) {
    return (
      configuration.active_environment ??
      environmentConfig?.active_environment ??
      null
    );
  }
  return environmentConfig?.configured
    ? environmentConfig.active_environment
    : null;
}

function isStaleEnvironmentError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /刷新|版本|revision|stale/i.test(message);
}

export function WorkspaceEnvironmentMapping({
  workspace,
  onClose,
  onEnvironmentChanged,
}: WorkspaceEnvironmentMappingProps) {
  const [configuration, setConfiguration] =
    useState<WorkspaceDatabaseEnvironmentMappings | null>(null);
  const [environmentConfig, setEnvironmentConfig] =
    useState<WorkspaceEnvironmentConfig | null>(null);
  const [panelTab, setPanelTab] =
    useState<EnvironmentPanelTab>("database-mappings");
  const [drafts, setDrafts] = useState<MappingDraft[]>([]);
  const [environmentJsonDrafts, setEnvironmentJsonDrafts] = useState<
    Record<DatabaseEnvironment, string>
  >({
    test: "{}",
    uat: "{}",
  });
  const [loading, setLoading] = useState(true);
  const [environmentConfigLoading, setEnvironmentConfigLoading] =
    useState(true);
  const [saving, setSaving] = useState(false);
  const [environmentConfigSaving, setEnvironmentConfigSaving] =
    useState(false);
  const [switching, setSwitching] = useState(false);
  const [editing, setEditing] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [environmentJsonDirty, setEnvironmentJsonDirty] = useState(false);
  const [onlyIssues, setOnlyIssues] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [environmentConfigError, setEnvironmentConfigError] = useState<
    string | null
  >(null);
  const [reloadRequired, setReloadRequired] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  function applyConfiguration(
    next: WorkspaceDatabaseEnvironmentMappings,
    options: { keepEditing?: boolean } = {},
  ) {
    setConfiguration(next);
    setDrafts(buildDrafts(next));
    setDirty(false);
    setEditing(
      options.keepEditing ??
        (!next.configured || next.summary.issue_count > 0),
    );
  }

  function applyEnvironmentConfiguration(next: WorkspaceEnvironmentConfig) {
    const values = { ...next.environments };
    if (
      next.configured &&
      next.active_environment &&
      next.active_config !== null
    ) {
      values[next.active_environment] = next.active_config;
    }
    setEnvironmentConfig(next);
    setEnvironmentJsonDrafts({
      test: formatEnvironmentJson(values.test),
      uat: formatEnvironmentJson(values.uat),
    });
    setEnvironmentJsonDirty(false);
  }

  function applyEnvironmentState(
    nextConfiguration: WorkspaceDatabaseEnvironmentMappings,
    nextEnvironmentConfig: WorkspaceEnvironmentConfig,
    options: { keepEditing?: boolean } = {},
  ) {
    applyConfiguration(nextConfiguration, options);
    applyEnvironmentConfiguration(nextEnvironmentConfig);
    onEnvironmentChanged?.(
      resolveActiveEnvironment(nextConfiguration, nextEnvironmentConfig),
    );
  }

  async function fetchEnvironmentState(): Promise<{
    configuration: WorkspaceDatabaseEnvironmentMappings;
    environmentConfig: WorkspaceEnvironmentConfig;
  }> {
    let [nextConfiguration, nextEnvironmentConfig] = await Promise.all([
      getWorkspaceDatabaseEnvironmentMappings(workspace.id),
      getWorkspaceEnvironmentConfig(workspace.id),
    ]);
    if (nextConfiguration.revision !== nextEnvironmentConfig.revision) {
      [nextConfiguration, nextEnvironmentConfig] = await Promise.all([
        getWorkspaceDatabaseEnvironmentMappings(workspace.id),
        getWorkspaceEnvironmentConfig(workspace.id),
      ]);
    }
    if (nextConfiguration.revision !== nextEnvironmentConfig.revision) {
      throw new Error("环境配置版本正在变化，请重新加载后重试。");
    }
    return {
      configuration: nextConfiguration,
      environmentConfig: nextEnvironmentConfig,
    };
  }

  async function loadEnvironmentState(
    options: {
      failureMessage?: string;
      keepEditing?: boolean;
      showLoading?: boolean;
    } = {},
  ): Promise<boolean> {
    const showLoading = options.showLoading ?? true;
    if (showLoading) {
      setLoading(true);
      setEnvironmentConfigLoading(true);
    }
    try {
      const next = await fetchEnvironmentState();
      applyEnvironmentState(next.configuration, next.environmentConfig, {
        keepEditing: options.keepEditing,
      });
      setError(null);
      setEnvironmentConfigError(null);
      setReloadRequired(false);
      return true;
    } catch (requestError) {
      const message =
        options.failureMessage ?? (requestError as Error).message;
      setError(message);
      setEnvironmentConfigError(message);
      setReloadRequired(true);
      return false;
    } finally {
      if (showLoading) {
        setLoading(false);
        setEnvironmentConfigLoading(false);
      }
    }
  }

  useEffect(() => {
    void loadEnvironmentState();
    // The modal is remounted for each workspace, so its identifier is stable
    // for the lifetime of this request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace.id]);

  const targetIndex = useMemo(() => {
    const index = new Map<string, DatabaseEnvironmentTarget>();
    configuration?.projects.forEach((project) => {
      ENVIRONMENTS.forEach((environment) => {
        project.candidates[environment].forEach((target) => {
          index.set(`${project.project_id}:${target.link_id}`, target);
        });
      });
      project.mappings.forEach((mapping) => {
        ENVIRONMENTS.forEach((environment) => {
          const target = mapping.targets[environment];
          const suggestion = mapping.suggested_targets[environment];
          if (target) {
            index.set(`${project.project_id}:${target.link_id}`, target);
          }
          if (suggestion) {
            index.set(`${project.project_id}:${suggestion.link_id}`, suggestion);
          }
        });
      });
    });
    return index;
  }, [configuration]);

  const aliasCounts = useMemo(() => {
    const counts = new Map<string, number>();
    drafts.forEach((draft) => {
      const alias = draft.mcpAlias.trim().toLocaleLowerCase();
      if (alias) counts.set(alias, (counts.get(alias) ?? 0) + 1);
    });
    return counts;
  }, [drafts]);

  const targetUseCounts = useMemo(() => {
    const counts = new Map<string, number>();
    drafts.forEach((draft) => {
      if (draft.testLinkId) {
        const key = `test:${draft.testLinkId}`;
        counts.set(key, (counts.get(key) ?? 0) + 1);
      }
      if (draft.uatLinkId) {
        const key = `uat:${draft.uatLinkId}`;
        counts.set(key, (counts.get(key) ?? 0) + 1);
      }
    });
    return counts;
  }, [drafts]);

  const evaluatedDrafts = useMemo<EvaluatedDraft[]>(
    () =>
      drafts.map((draft) => {
        const issues: string[] = [];
        const normalizedAlias = draft.mcpAlias.trim().toLocaleLowerCase();
        const testTarget = environmentTarget(draft, "test", targetIndex);
        const uatTarget = environmentTarget(draft, "uat", targetIndex);

        if (!draft.logicalName.trim()) issues.push("逻辑数据库名称不能为空");
        if (!normalizedAlias) issues.push(ISSUE_LABELS.missing_mcp_alias);
        if (normalizedAlias && !MCP_ALIAS_PATTERN.test(draft.mcpAlias.trim())) {
          issues.push("MCP 别名格式不正确");
        }
        if (normalizedAlias && (aliasCounts.get(normalizedAlias) ?? 0) > 1) {
          issues.push(ISSUE_LABELS.alias_conflict);
        }
        if (!testTarget) issues.push(ISSUE_LABELS.missing_test);
        if (!uatTarget) issues.push(ISSUE_LABELS.missing_uat);
        if (
          draft.testLinkId &&
          (targetUseCounts.get(`test:${draft.testLinkId}`) ?? 0) > 1
        ) {
          issues.push("TEST 数据库授权被重复映射");
        }
        if (
          draft.uatLinkId &&
          (targetUseCounts.get(`uat:${draft.uatLinkId}`) ?? 0) > 1
        ) {
          issues.push("UAT 数据库授权被重复映射");
        }
        if (
          testTarget &&
          uatTarget &&
          testTarget.engine !== uatTarget.engine
        ) {
          issues.push(ISSUE_LABELS.engine_mismatch);
        }
        if (
          testTarget &&
          uatTarget &&
          testTarget.namespace_type !== uatTarget.namespace_type
        ) {
          issues.push(ISSUE_LABELS.namespace_mismatch);
        }

        ENVIRONMENTS.forEach((environment) => {
          const target =
            environment === "test" ? testTarget : uatTarget;
          if (!target) return;
          const label = ENVIRONMENT_LABELS[environment];
          if (!target.source_enabled) issues.push(`${label} 数据源已停用`);
          if (!target.available) issues.push(`${label} 数据库不可用`);
          if (!target.link_enabled) issues.push(`${label} 授权已停用`);
          if (!target.readonly) issues.push(`${label} 授权不是只读`);
          if (target.system_database) issues.push(`${label} 是系统数据库`);
        });

        if (
          !mappingChanged(draft) &&
          !["complete", "suggested"].includes(draft.source.status)
        ) {
          const serverIssues =
            draft.source.issues.length > 0
              ? draft.source.issues
              : [draft.source.status];
          serverIssues.forEach((issue) => issues.push(issueLabel(issue)));
        }

        return {
          draft,
          issues: Array.from(new Set(issues)),
        };
      }),
    [aliasCounts, drafts, targetIndex, targetUseCounts],
  );

  const visibleDrafts = onlyIssues
    ? evaluatedDrafts.filter((row) => row.issues.length > 0)
    : evaluatedDrafts;
  const completeCount = evaluatedDrafts.filter(
    (row) => row.issues.length === 0,
  ).length;
  const issueCount = evaluatedDrafts.length - completeCount;
  const hasMappingIssues = issueCount > 0;
  const backendProjectCount =
    configuration?.projects.filter(
      (project) => project.project_kind === "backend",
    ).length ?? 0;
  const parsedEnvironmentJson = useMemo(
    () => ({
      test: parseEnvironmentJson(environmentJsonDrafts.test),
      uat: parseEnvironmentJson(environmentJsonDrafts.uat),
    }),
    [environmentJsonDrafts],
  );
  const environmentJsonTotalBytes = useMemo(
    () =>
      environmentJsonByteLength([
        environmentJsonDrafts.test,
        environmentJsonDrafts.uat,
      ]),
    [environmentJsonDrafts],
  );
  const environmentJsonTooLarge =
    environmentJsonTotalBytes > ENVIRONMENT_JSON_TOTAL_MAX_BYTES;
  const environmentJsonHasErrors =
    environmentJsonTooLarge ||
    ENVIRONMENTS.some(
      (environment) => !parsedEnvironmentJson[environment].ok,
    );
  const environmentJsonTotalKiB = (
    environmentJsonTotalBytes / 1024
  ).toFixed(
    environmentJsonTotalBytes < 10 * 1024 ? 1 : 0,
  );

  function updateDraft(
    key: string,
    change: Partial<
      Pick<
        MappingDraft,
        "logicalName" | "mcpAlias" | "testLinkId" | "uatLinkId"
      >
    >,
  ) {
    setDrafts((current) =>
      current.map((draft) =>
        draft.key === key ? { ...draft, ...change } : draft,
      ),
    );
    setDirty(true);
    setNotice(null);
    setError(null);
  }

  function resetDrafts() {
    if (!configuration) return;
    setDrafts(buildDrafts(configuration));
    setDirty(false);
    setEditing(false);
    setError(null);
    setNotice(null);
  }

  function updateEnvironmentJson(
    environment: DatabaseEnvironment,
    value: string,
  ) {
    setEnvironmentJsonDrafts((current) => ({
      ...current,
      [environment]: value,
    }));
    setEnvironmentJsonDirty(true);
    setEnvironmentConfigError(null);
    setNotice(null);
  }

  function resetEnvironmentJson() {
    if (!environmentConfig) return;
    applyEnvironmentConfiguration(environmentConfig);
    setEnvironmentConfigError(null);
    setNotice(null);
  }

  function applySuggestions() {
    let applied = 0;
    const nextDrafts = drafts.map((draft) => {
      const suggestion = draft.source.suggested_targets;
      const nextTest = draft.testLinkId || suggestion.test?.link_id || "";
      const nextUat = draft.uatLinkId || suggestion.uat?.link_id || "";
      if (
        nextTest !== draft.testLinkId ||
        nextUat !== draft.uatLinkId
      ) {
        applied += 1;
        return {
          ...draft,
          testLinkId: nextTest,
          uatLinkId: nextUat,
        };
      }
      return draft;
    });
    setDrafts(nextDrafts);
    setEditing(true);
    setError(null);
    if (applied > 0) {
      setDirty(true);
      setNotice(`已应用 ${applied} 条同后缀匹配建议，请确认后保存。`);
    } else {
      setNotice("当前没有可以自动应用的新建议。");
    }
  }

  async function saveMappings() {
    if (!configuration) return;
    if (environmentJsonDirty) {
      setError("环境 JSON 还有未保存修改，请先保存或重置后再保存数据库映射。");
      return;
    }
    if (evaluatedDrafts.length === 0) {
      setError("请先应用自动匹配建议，再保存环境映射。");
      return;
    }
    if (hasMappingIssues) {
      setOnlyIssues(true);
      setError(
        "映射仍有缺失目标、不可用数据库或类型冲突，请处理所有问题后再保存。",
      );
      return;
    }

    setSaving(true);
    try {
      const next = await replaceWorkspaceDatabaseEnvironmentMappings(
        workspace.id,
        {
          expected_revision: configuration.revision,
          mappings: drafts
            .filter((draft) => draft.testLinkId || draft.uatLinkId)
            .map((draft) => ({
              ...(draft.id ? { id: draft.id } : {}),
              project_id: draft.projectId,
              logical_name: draft.logicalName.trim(),
              mcp_alias: draft.mcpAlias.trim(),
              targets: {
                test: draft.testLinkId || null,
                uat: draft.uatLinkId || null,
              },
            })),
        },
      );
      applyConfiguration(next, { keepEditing: false });
      setError(null);
      setNotice(
        "环境映射已保存，当前环境没有自动切换；已有 MCP 任务需要重新 prepare。",
      );
      await loadEnvironmentState({
        failureMessage:
          "数据库映射已保存，但共享环境版本同步失败，请重新加载。",
        keepEditing: false,
        showLoading: false,
      });
    } catch (requestError) {
      setError((requestError as Error).message);
      if (isStaleEnvironmentError(requestError)) {
        setReloadRequired(true);
      }
    } finally {
      setSaving(false);
    }
  }

  async function saveEnvironmentJson() {
    if (!environmentConfig) return;
    if (dirty) {
      setEnvironmentConfigError(
        "数据库映射还有未保存修改，请先保存或取消编辑后再保存环境 JSON。",
      );
      return;
    }
    if (environmentJsonTooLarge) {
      setEnvironmentConfigError(
        "TEST 与 UAT 环境 JSON 合计不能超过 256 KiB，请精简后再保存。",
      );
      return;
    }
    if (environmentJsonHasErrors) {
      setEnvironmentConfigError(
        "请先修正 TEST 和 UAT 的 JSON，顶层必须是对象。",
      );
      return;
    }
    const testResult = parsedEnvironmentJson.test;
    const uatResult = parsedEnvironmentJson.uat;
    if (!testResult.ok || !uatResult.ok) return;

    setEnvironmentConfigSaving(true);
    try {
      const next = await replaceWorkspaceEnvironmentConfig(workspace.id, {
        expected_revision: environmentConfig.revision,
        environments: {
          test: testResult.value,
          uat: uatResult.value,
        },
      });
      applyEnvironmentConfiguration(next);
      onEnvironmentChanged?.(
        resolveActiveEnvironment(configuration, next),
      );
      setEnvironmentConfigError(null);
      setNotice(
        "环境 JSON 已保存，当前环境没有自动切换；已有 MCP 任务需要重新 prepare。",
      );
      await loadEnvironmentState({
        failureMessage:
          "环境 JSON 已保存，但共享环境版本同步失败，请重新加载。",
        keepEditing: editing,
        showLoading: false,
      });
    } catch (requestError) {
      setEnvironmentConfigError((requestError as Error).message);
      if (isStaleEnvironmentError(requestError)) {
        setReloadRequired(true);
      }
    } finally {
      setEnvironmentConfigSaving(false);
    }
  }

  function environmentReady(environment: DatabaseEnvironment): boolean {
    const persistedMappings = evaluatedDrafts.filter(
      ({ draft }) => draft.id !== null,
    );
    if (persistedMappings.length === 0) {
      return Boolean(
        configuration?.configured || environmentConfig?.configured,
      );
    }
    return persistedMappings.every(({ draft, issues }) => {
      const target = environmentTarget(draft, environment, targetIndex);
      return Boolean(
        issues.length === 0 &&
          draft.logicalName.trim() &&
          draft.mcpAlias.trim() &&
          target &&
          targetAvailable(target),
      );
    });
  }

  async function switchEnvironment(environment: DatabaseEnvironment) {
    if (!configuration || environment === activeEnvironment) {
      return;
    }
    if (dirty) {
      setError("当前有未保存的映射，请先保存后再切换环境。");
      setPanelTab("database-mappings");
      return;
    }
    if (environmentJsonDirty) {
      setEnvironmentConfigError(
        "当前有未保存的环境 JSON，请先保存或重置后再切换环境。",
      );
      setPanelTab("environment-json");
      return;
    }
    if (!environmentReady(environment)) {
      if (configuration.configured) {
        setError(
          `${ENVIRONMENT_LABELS[environment]} 映射尚不完整或目标不可用，暂时不能切换。`,
        );
        setOnlyIssues(true);
        setPanelTab("database-mappings");
      } else {
        setEnvironmentConfigError(
          "请先分别保存 TEST 与 UAT 环境 JSON，再切换环境。",
        );
        setPanelTab("environment-json");
      }
      return;
    }
    if (
      !window.confirm(
        `确定切换到 ${ENVIRONMENT_LABELS[environment]} 吗？切换后已有 MCP 任务需要重新 prepare，避免静默换环境。`,
      )
    ) {
      return;
    }

    setSwitching(true);
    try {
      const next = await setWorkspaceDatabaseEnvironment(workspace.id, {
        environment,
        expected_revision: configuration.revision,
      });
      applyConfiguration(next, { keepEditing: false });
      onEnvironmentChanged?.(
        resolveActiveEnvironment(next, environmentConfig),
      );
      setError(null);
      setNotice(
        `已切换到 ${ENVIRONMENT_LABELS[environment]}；已有 MCP 任务需要重新 prepare 后再访问数据库。`,
      );
      await loadEnvironmentState({
        failureMessage:
          "环境已切换，但共享环境版本同步失败，请重新加载。",
        keepEditing: false,
        showLoading: false,
      });
    } catch (requestError) {
      setError((requestError as Error).message);
      if (isStaleEnvironmentError(requestError)) {
        setReloadRequired(true);
      }
    } finally {
      setSwitching(false);
    }
  }

  function requestReload() {
    if (
      (dirty || environmentJsonDirty) &&
      !window.confirm("重新加载会丢弃当前未保存修改，确定继续吗？")
    ) {
      return;
    }
    setNotice(null);
    void loadEnvironmentState();
  }

  function requestClose() {
    if (
      (dirty || environmentJsonDirty) &&
      !window.confirm("还有未保存的环境配置，确定直接关闭吗？")
    ) {
      return;
    }
    onClose();
  }

  function candidatesFor(
    projectId: string,
    environment: DatabaseEnvironment,
    selectedLinkId: string,
  ): DatabaseEnvironmentTarget[] {
    const project = configuration?.projects.find(
      (item) => item.project_id === projectId,
    );
    const candidates = [...(project?.candidates[environment] ?? [])];
    const selected = selectedLinkId
      ? targetIndex.get(`${projectId}:${selectedLinkId}`)
      : null;
    if (
      selected &&
      !candidates.some((candidate) => candidate.link_id === selected.link_id)
    ) {
      candidates.unshift(selected);
    }
    return candidates;
  }

  const activeEnvironment = resolveActiveEnvironment(
    configuration,
    environmentConfig,
  );
  const selectorConfigured = Boolean(
    configuration?.configured || environmentConfig?.configured,
  );
  const selectorEnabled = Boolean(
    configuration?.enabled || environmentConfig?.configured,
  );
  const nextEnvironment: DatabaseEnvironment =
    activeEnvironment === "test" ? "uat" : "test";
  const switchDisabled =
    !configuration ||
    !selectorConfigured ||
    !selectorEnabled ||
    dirty ||
    environmentJsonDirty ||
    loading ||
    saving ||
    environmentConfigLoading ||
    environmentConfigSaving ||
    switching ||
    !environmentReady(nextEnvironment);

  return (
    <div className="environment-mapping-modal" role="presentation">
      <section
        className="environment-mapping-panel"
        role="dialog"
        aria-modal="true"
        aria-label={`${workspace.name} 工作空间环境配置`}
      >
        <header className="environment-mapping-header">
          <div>
            <span className="file-chip">环境切换</span>
            <h2>工作空间环境配置</h2>
            <p>
              分别维护数据库映射和通用环境 JSON，切换时统一选择 TEST 或 UAT。
            </p>
          </div>
          <div className="environment-mapping-header-actions">
            <div className="active-environment-summary">
              <span>当前环境</span>
              <strong
                data-environment={activeEnvironment ?? "unconfigured"}
              >
                {activeEnvironment
                  ? ENVIRONMENT_LABELS[activeEnvironment]
                  : "未配置"}
              </strong>
            </div>
            <button
              type="button"
              className="secondary-button environment-switch-button"
              disabled={switchDisabled}
              title={
                dirty
                  ? "请先保存当前映射"
                  : environmentJsonDirty
                    ? "请先保存或重置环境 JSON"
                    : !selectorConfigured
                      ? "请先保存数据库映射或 TEST / UAT 环境 JSON"
                      : !selectorEnabled
                        ? "环境选择器尚未启用"
                    : !environmentReady(nextEnvironment)
                      ? configuration?.configured
                        ? `${ENVIRONMENT_LABELS[nextEnvironment]} 映射不完整或目标不可用`
                        : "请先完整保存 TEST / UAT 环境 JSON"
                      : undefined
              }
              onClick={() => void switchEnvironment(nextEnvironment)}
            >
              {switching
                ? "正在切换…"
                : `切换到 ${ENVIRONMENT_LABELS[nextEnvironment]}`}
            </button>
            <button
              type="button"
              className="close-button"
              aria-label="关闭工作空间环境配置"
              disabled={saving || environmentConfigSaving || switching}
              onClick={requestClose}
            >
              ×
            </button>
          </div>
        </header>

        <div className="environment-mapping-guidance">
          <strong>切换规则</strong>
          <span>
            保存数据库映射、保存环境 JSON 或切换环境后，已有 MCP 任务都需要重新
            prepare，避免静默换用配置。
          </span>
        </div>

        <nav
          className="environment-config-tabs"
          role="tablist"
          aria-label="环境配置类型"
        >
          <button
            type="button"
            role="tab"
            aria-selected={panelTab === "database-mappings"}
            data-active={panelTab === "database-mappings"}
            onClick={() => setPanelTab("database-mappings")}
          >
            数据库映射
            <small>{evaluatedDrafts.length}</small>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={panelTab === "environment-json"}
            data-active={panelTab === "environment-json"}
            onClick={() => setPanelTab("environment-json")}
          >
            环境 JSON
          </button>
        </nav>

        <div className="environment-mapping-content">
          {notice ? (
            <div className="environment-mapping-notice" role="status">
              {notice}
            </div>
          ) : null}

          {reloadRequired ? (
            <div
              className="error-banner environment-mapping-error"
              role="alert"
            >
              <span>
                页面中的数据库映射与环境 JSON 可能不是同一版本，请重新加载全部。
              </span>
              <button
                type="button"
                className="secondary-button"
                disabled={loading || environmentConfigLoading}
                onClick={requestReload}
              >
                {loading || environmentConfigLoading
                  ? "正在加载…"
                  : "重新加载全部"}
              </button>
            </div>
          ) : null}

          {panelTab === "database-mappings" ? (
            <>
              {loading ? (
                <p className="empty-message">正在读取项目环境映射…</p>
              ) : null}

              {error ? (
                <div
                  className="error-banner environment-mapping-error"
                  role="alert"
                >
                  <span>{error}</span>
                  {!configuration && !reloadRequired ? (
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={loading || environmentConfigLoading}
                      onClick={requestReload}
                    >
                      {loading || environmentConfigLoading
                        ? "正在加载…"
                        : "重新加载全部"}
                    </button>
                  ) : null}
                </div>
              ) : null}

              {!loading && configuration ? (
                <>
              <div className="environment-mapping-toolbar">
                <div className="environment-mapping-counts">
                  <span>
                    <strong>{evaluatedDrafts.length}</strong> 项映射
                  </span>
                  <span data-status="complete">
                    <strong>{completeCount}</strong> 项完整
                  </span>
                  <span data-status={issueCount > 0 ? "issue" : "complete"}>
                    <strong>{issueCount}</strong> 项待处理
                  </span>
                </div>
                <div className="environment-mapping-actions">
                  <label className="environment-issues-filter">
                    <input
                      type="checkbox"
                      checked={onlyIssues}
                      onChange={(event) =>
                        setOnlyIssues(event.target.checked)
                      }
                    />
                    只看问题
                  </label>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={saving || switching || drafts.length === 0}
                    onClick={applySuggestions}
                  >
                    自动匹配同后缀
                  </button>
                  {editing ? (
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={saving || switching}
                      onClick={resetDrafts}
                    >
                      取消编辑
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={drafts.length === 0}
                      onClick={() => setEditing(true)}
                    >
                      编辑映射
                    </button>
                  )}
                </div>
              </div>

              {backendProjectCount === 0 ? (
                <div className="environment-mapping-empty">
                  <h3>当前工作空间还没有可配置的后端项目</h3>
                  <p>环境数据库映射不会包含前端项目。</p>
                </div>
              ) : evaluatedDrafts.length === 0 ? (
                <div className="environment-mapping-empty">
                  <h3>还没有可建立映射的数据库授权</h3>
                  <p>
                    请先在后端项目的“管理数据源”中授权 TEST 和 UAT 数据库。
                  </p>
                </div>
              ) : visibleDrafts.length === 0 ? (
                <div className="environment-mapping-empty">
                  <h3>当前没有需要处理的映射</h3>
                  <p>关闭“只看问题”可以查看全部项目映射。</p>
                </div>
              ) : (
                <div
                  className="environment-mapping-table"
                  role="table"
                  aria-label="项目 TEST 和 UAT 数据库映射"
                >
                  <div
                    className="environment-mapping-table-header"
                    role="row"
                  >
                    <span role="columnheader">项目 / 逻辑别名</span>
                    <span role="columnheader">TEST 数据库</span>
                    <span role="columnheader">UAT 数据库</span>
                    <span role="columnheader">状态</span>
                  </div>
                  <div className="environment-mapping-table-body">
                    {visibleDrafts.map(({ draft, issues }) => {
                      const testTarget = environmentTarget(
                        draft,
                        "test",
                        targetIndex,
                      );
                      const uatTarget = environmentTarget(
                        draft,
                        "uat",
                        targetIndex,
                      );
                      return (
                        <div
                          className="environment-mapping-row"
                          data-status={
                            issues.length === 0 ? "complete" : "issue"
                          }
                          role="row"
                          key={draft.key}
                        >
                          <div
                            className="environment-mapping-identity"
                            role="cell"
                          >
                            <strong>{draft.projectName}</strong>
                            {editing ? (
                              <>
                                <label>
                                  <span>逻辑名称</span>
                                  <input
                                    value={draft.logicalName}
                                    onChange={(event) =>
                                      updateDraft(draft.key, {
                                        logicalName: event.target.value,
                                      })
                                    }
                                  />
                                </label>
                                <label>
                                  <span>MCP 别名</span>
                                  <input
                                    className="environment-alias-input"
                                    value={draft.mcpAlias}
                                    onChange={(event) =>
                                      updateDraft(draft.key, {
                                        mcpAlias: event.target.value,
                                      })
                                    }
                                  />
                                </label>
                              </>
                            ) : (
                              <>
                                <span>{draft.logicalName || "未设置逻辑名称"}</span>
                                <code>{draft.mcpAlias || "未设置 MCP 别名"}</code>
                              </>
                            )}
                          </div>

                          {ENVIRONMENTS.map((environment) => {
                            const selectedTarget =
                              environment === "test"
                                ? testTarget
                                : uatTarget;
                            const selectedLinkId =
                              environment === "test"
                                ? draft.testLinkId
                                : draft.uatLinkId;
                            const suggestion =
                              draft.source.suggested_targets[environment];
                            return (
                              <div
                                className="environment-target-cell"
                                data-active={
                                  activeEnvironment === environment
                                }
                                role="cell"
                                key={environment}
                              >
                                {editing ? (
                                  <label>
                                    <span className="sr-only">
                                      {draft.projectName}{" "}
                                      {ENVIRONMENT_LABELS[environment]} 数据库
                                    </span>
                                    <select
                                      aria-label={`${draft.projectName} ${draft.logicalName} ${ENVIRONMENT_LABELS[environment]} 数据库`}
                                      value={selectedLinkId}
                                      onChange={(event) =>
                                        updateDraft(
                                          draft.key,
                                          environment === "test"
                                            ? {
                                                testLinkId:
                                                  event.target.value,
                                              }
                                            : {
                                                uatLinkId:
                                                  event.target.value,
                                              },
                                        )
                                      }
                                    >
                                      <option value="">未配置</option>
                                      {candidatesFor(
                                        draft.projectId,
                                        environment,
                                        selectedLinkId,
                                      ).map((candidate) => (
                                        <option
                                          value={candidate.link_id}
                                          disabled={
                                            !targetAvailable(candidate) &&
                                            candidate.link_id !== selectedLinkId
                                          }
                                          key={candidate.link_id}
                                        >
                                          {targetTitle(candidate)} ·{" "}
                                          {candidate.data_source_name}
                                        </option>
                                      ))}
                                    </select>
                                  </label>
                                ) : selectedTarget ? (
                                  <>
                                    <strong>{targetTitle(selectedTarget)}</strong>
                                    <code>{selectedTarget.database_name}</code>
                                    <small>
                                      {selectedTarget.data_source_name} ·{" "}
                                      {selectedTarget.engine.toUpperCase()}
                                    </small>
                                  </>
                                ) : (
                                  <>
                                    <strong className="environment-target-missing">
                                      未配置
                                    </strong>
                                    {suggestion ? (
                                      <small>
                                        建议：{targetTitle(suggestion)}
                                      </small>
                                    ) : (
                                      <small>没有可用的同后缀候选</small>
                                    )}
                                  </>
                                )}
                              </div>
                            );
                          })}

                          <div className="environment-mapping-status" role="cell">
                            <span
                              data-status={
                                issues.length === 0 ? "complete" : "issue"
                              }
                            >
                              {issues.length === 0 ? "已匹配" : "待处理"}
                            </span>
                            {issues.slice(0, 3).map((issue) => (
                              <small key={issue}>{issue}</small>
                            ))}
                            {issues.length > 3 ? (
                              <small>另有 {issues.length - 3} 个问题</small>
                            ) : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
                </>
              ) : null}
            </>
          ) : (
            <>
              {environmentConfigLoading ? (
                <p className="empty-message">正在读取环境 JSON…</p>
              ) : null}

              {environmentConfigError ? (
                <div
                  className="error-banner environment-mapping-error"
                  role="alert"
                >
                  <span>{environmentConfigError}</span>
                  {!environmentConfig && !reloadRequired ? (
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={loading || environmentConfigLoading}
                      onClick={requestReload}
                    >
                      {loading || environmentConfigLoading
                        ? "正在加载…"
                        : "重新加载全部"}
                    </button>
                  ) : null}
                </div>
              ) : null}

              {!environmentConfigLoading && environmentConfig ? (
                <section className="environment-json-section">
                  <header className="environment-json-intro">
                    <div>
                      <span className="file-chip">通用 JSON</span>
                      <h3>TEST / UAT 环境配置</h3>
                      <p>
                        保存任意字段的 JSON 对象，不预设 MQ、ES、MinIO
                        或其他组件字段；两套配置合计最多 256 KiB。
                      </p>
                    </div>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={
                        !environmentJsonDirty ||
                        environmentConfigSaving ||
                        switching
                      }
                      onClick={resetEnvironmentJson}
                    >
                      重置 JSON
                    </button>
                  </header>

                  {!environmentConfig.configured ? (
                    <div className="environment-json-prerequisite" role="status">
                      这是首次维护环境 JSON；首次保存会启用环境配置，并默认以
                      UAT 作为当前环境。
                    </div>
                  ) : null}

                  <div className="environment-json-editors">
                    {ENVIRONMENTS.map((environment) => {
                      const result = parsedEnvironmentJson[environment];
                      const isActive = activeEnvironment === environment;
                      return (
                        <article
                          className="environment-json-editor"
                          data-active={isActive}
                          key={environment}
                        >
                          <header>
                            <div>
                              <strong>
                                {ENVIRONMENT_LABELS[environment]}
                              </strong>
                              <span>
                                {isActive
                                  ? environmentJsonDirty
                                    ? "当前环境 · 有待保存修改"
                                    : "当前生效 JSON"
                                  : "备用环境 JSON"}
                              </span>
                            </div>
                            {isActive ? (
                              <span
                                className="environment-json-active-chip"
                                data-environment={environment}
                              >
                                当前
                              </span>
                            ) : null}
                          </header>
                          <textarea
                            aria-label={`${ENVIRONMENT_LABELS[environment]} 环境 JSON`}
                            aria-invalid={!result.ok}
                            disabled={
                              environmentConfigSaving ||
                              saving ||
                              switching
                            }
                            spellCheck={false}
                            value={environmentJsonDrafts[environment]}
                            onChange={(event) =>
                              updateEnvironmentJson(
                                environment,
                                event.target.value,
                              )
                            }
                          />
                          <footer data-status={result.ok ? "valid" : "invalid"}>
                            <span>
                              {result.ok
                                ? "JSON 语法有效"
                                : result.error}
                            </span>
                            <small>
                              {environmentJsonDrafts[environment].length} 字符
                            </small>
                          </footer>
                        </article>
                      );
                    })}
                  </div>

                  <div className="environment-json-privacy-note">
                    <span>
                      环境 JSON 可以包含服务地址和访问凭据，并会随 prepare
                      返回给本机 MCP 客户端。仅限在可信本机环境中使用；前端不会将内容写入日志。
                    </span>
                    <strong
                      data-status={
                        environmentJsonTooLarge ? "invalid" : "valid"
                      }
                      role={environmentJsonTooLarge ? "alert" : undefined}
                    >
                      合计 {environmentJsonTotalKiB} KiB / 256 KiB
                    </strong>
                  </div>
                </section>
              ) : null}
            </>
          )}
        </div>

        <footer className="environment-mapping-footer">
          <span>
            {panelTab === "database-mappings"
              ? "保存映射不会自动切换当前环境，但已有 MCP 任务需要重新 prepare。"
              : "保存 JSON 不会自动切换当前环境，也不会输出 JSON 内容到日志。"}
          </span>
          <div>
            <button
              type="button"
              className="secondary-button"
              disabled={
                saving ||
                environmentConfigSaving ||
                switching
              }
              onClick={requestClose}
            >
              关闭
            </button>
            {panelTab === "database-mappings" ? (
              <button
                type="button"
                className="primary-button"
                disabled={
                  !configuration ||
                  !dirty ||
                  environmentJsonDirty ||
                  hasMappingIssues ||
                  saving ||
                  environmentConfigSaving ||
                  switching
                }
                onClick={() => void saveMappings()}
              >
                {saving ? "正在保存…" : "保存映射"}
              </button>
            ) : (
              <button
                type="button"
                className="primary-button"
                disabled={
                  !environmentConfig ||
                  !environmentJsonDirty ||
                  dirty ||
                  environmentJsonHasErrors ||
                  saving ||
                  environmentConfigSaving ||
                  switching
                }
                onClick={() => void saveEnvironmentJson()}
              >
                {environmentConfigSaving
                  ? "正在保存…"
                  : "保存环境 JSON"}
              </button>
            )}
          </div>
        </footer>
      </section>
    </div>
  );
}
