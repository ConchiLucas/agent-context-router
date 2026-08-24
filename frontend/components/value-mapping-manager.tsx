"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { getValueMappingOverview, listWorkspaces } from "@/lib/api";
import type {
  ValueMappingBinding,
  ValueMappingOverview,
  WorkspaceSummary,
} from "@/lib/types";

function bindingKey(binding: Pick<ValueMappingBinding, "interface_id" | "location" | "parameter_path">) {
  return `${binding.interface_id}:${binding.location}:${binding.parameter_path}`;
}

function ReadOnlyField({
  label,
  value,
  code = false,
  multiline = false,
  wide = false,
}: {
  label: string;
  value: string;
  code?: boolean;
  multiline?: boolean;
  wide?: boolean;
}) {
  return (
    <div className={`value-mapping-readonly-field${wide ? " value-mapping-wide" : ""}`}>
      <span>{label}</span>
      <div
        className={`${code ? " value-mapping-code-input" : ""}${multiline ? " value-mapping-readonly-field--multiline" : ""}`}
      >
        {value || "—"}
      </div>
    </div>
  );
}

export function ValueMappingManager() {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [overview, setOverview] = useState<ValueMappingOverview | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void listWorkspaces()
      .then((items) => {
        if (cancelled) return;
        setWorkspaces(items);
        setWorkspaceId((current) => current || items[0]?.id || "");
      })
      .catch((reason: Error) => setError(reason.message));
    return () => {
      cancelled = true;
    };
  }, []);

  const load = useCallback(
    async (nextKeyword = keyword) => {
      if (!workspaceId) return;
      setLoading(true);
      setError("");
      try {
        const mappingResult = await getValueMappingOverview(workspaceId, nextKeyword);
        setOverview(mappingResult);
        setSelectedId((current) =>
          mappingResult.mappings.some((item) => item.id === current)
            ? current
            : mappingResult.mappings[0]?.id ?? "",
        );
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "映射数据加载失败");
      } finally {
        setLoading(false);
      }
    },
    [keyword, workspaceId],
  );

  useEffect(() => {
    setSelectedId("");
    if (workspaceId) void load("");
  }, [workspaceId]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeMapping = useMemo(
    () => overview?.mappings.find((item) => item.id === selectedId) ?? null,
    [overview?.mappings, selectedId],
  );

  const databaseAliasLabel = useMemo(() => {
    if (!activeMapping) return "";
    const option = overview?.database_aliases.find(
      (item) => item.value === activeMapping.database_alias,
    );
    return option ? `${option.label} · ${option.value}` : activeMapping.database_alias;
  }, [activeMapping, overview?.database_aliases]);

  return (
    <section className="value-mapping-page">
      <header className="value-mapping-heading">
        <div>
          <p className="eyebrow">VALUE MAPPING</p>
          <h1>映射管理</h1>
          <p>查看常用业务值的取值方式，以及哪些接口参数需要这个值。</p>
        </div>
        <label>
          工作空间
          <select value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)}>
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
            ))}
          </select>
        </label>
      </header>

      <div className="value-mapping-toolbar">
        <div className="value-mapping-search">
          <input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && void load(keyword)}
            placeholder="搜索业务值、value_key 或关键词别名"
          />
          <button className="secondary-button" type="button" onClick={() => void load(keyword)}>
            搜索
          </button>
        </div>
      </div>

      {error ? <p className="error-banner" role="alert">{error}</p> : null}

      <div className="value-mapping-layout">
        <aside className="value-mapping-list" aria-label="业务值映射列表">
          <header>
            <strong>业务值</strong>
            <span>{overview?.mappings.length ?? 0}</span>
          </header>
          {loading ? <p className="value-mapping-list-state">正在加载映射…</p> : null}
          {!loading && overview?.mappings.length === 0 ? (
            <div className="value-mapping-list-state">
              <strong>还没有映射</strong>
              <span>映射由 AI 或运维接口维护。</span>
            </div>
          ) : null}
          {overview?.mappings.map((mapping) => (
            <button
              key={mapping.id}
              type="button"
              data-active={selectedId === mapping.id}
              onClick={() => {
                setSelectedId(mapping.id);
                setError("");
              }}
            >
              <span>
                <strong title={mapping.name}>{mapping.name}</strong>
                <code>{mapping.value_key}</code>
              </span>
              <span>
                <small data-status={mapping.status}>{mapping.status === "published" ? "已发布" : "草稿"}</small>
                <small>{mapping.binding_count} 个参数</small>
              </span>
            </button>
          ))}
        </aside>

        <section className="value-mapping-editor">
          {!activeMapping ? (
            <div className="value-mapping-empty">
              <strong>选择一个映射</strong>
              <p>这里仅展示由 AI 维护的业务含义、数据库取值规则和接口参数绑定。</p>
            </div>
          ) : (
            <>
              <header>
                <div>
                  <h2>{activeMapping.name || "未命名映射"}</h2>
                  <p>版本 {activeMapping.version}</p>
                </div>
              </header>

              <div className="value-mapping-section">
                <div className="value-mapping-section-heading">
                  <div><h3>业务值定义</h3><p>关键词用于 AI 搜索，value_key 是稳定机器标识。</p></div>
                </div>
                <div className="value-mapping-form-grid">
                  <ReadOnlyField label="业务名称" value={activeMapping.name} />
                  <ReadOnlyField label="value_key" value={activeMapping.value_key} code />
                  <ReadOnlyField label="关键词别名" value={activeMapping.aliases.join("\n")} multiline wide />
                  <ReadOnlyField label="用途说明" value={activeMapping.description} multiline wide />
                </div>
              </div>

              <div className="value-mapping-section">
                <div className="value-mapping-section-heading">
                  <div><h3>数据库取值规则</h3><p>展示数据库别名、表和字段；环境地址由未来 MCP 调用时解析。</p></div>
                  <code>database_column</code>
                </div>
                {overview?.database_aliases.length === 0 ? (
                  <p className="value-mapping-inline-warning">当前工作空间没有可查询的只读数据库别名，AI 暂时无法解析候选值。</p>
                ) : null}
                <div className="value-mapping-form-grid">
                  <ReadOnlyField label="数据库别名" value={databaseAliasLabel} code />
                  <ReadOnlyField label="表名" value={activeMapping.table_name} code />
                  <ReadOnlyField label="取值字段" value={activeMapping.value_column} code />
                  <ReadOnlyField label="可搜索字段" value={activeMapping.search_columns.join(", ")} code wide />
                  <ReadOnlyField label="候选值展示字段" value={activeMapping.display_columns.join(", ")} code wide />
                  <ReadOnlyField label="固定过滤条件" value={JSON.stringify(activeMapping.filters, null, 2)} code multiline wide />
                </div>
                <p id="value-mapping-filter-help" className="value-mapping-help">JSON 对象，只支持等值条件。例如：{`{"status": 1}`}</p>
              </div>

              <div className="value-mapping-section">
                <div className="value-mapping-section-heading">
                  <div><h3>接口参数绑定</h3><p>以后既可以按关键词找到取值方式，也可以从接口参数反查。</p></div>
                  <span>{activeMapping.bindings.length} 个参数</span>
                </div>
                {activeMapping.bindings.length ? (
                  <ul className="value-mapping-binding-list">
                    {activeMapping.bindings.map((binding) => (
                      <li key={bindingKey(binding)}>
                        <div><strong title={binding.interface_name}>{binding.interface_name ?? binding.interface_id}</strong><span><code>{binding.method}</code> {binding.service_name} · {binding.controller_name}</span><code title={binding.interface_path}>{binding.location}.{binding.parameter_path} · {binding.interface_path}</code></div>
                      </li>
                    ))}
                  </ul>
                ) : <p className="value-mapping-section-empty">暂未绑定接口参数。</p>}
              </div>

            </>
          )}
        </section>
      </div>
    </section>
  );
}
