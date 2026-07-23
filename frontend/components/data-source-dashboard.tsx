"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  createDataSource,
  createDataSourceDatabase,
  deleteDataSource,
  deleteDataSourceDatabase,
  listDataSourceDatabases,
  listDataSourceEngineCapabilities,
  listDataSources,
  revealDataSourcePassword,
  syncDataSourceDatabases,
  testDataSourceConnection,
  updateDataSource,
} from "@/lib/api";
import type {
  DatabaseEngine,
  DataSourceEngineCapability,
  DataSourceDatabaseSummary,
  DataSourcePayload,
  DataSourceSummary,
} from "@/lib/types";
import {
  clickHouseConfigFromFields,
  clickHouseFieldsFromConfig,
  supportsConnectionTest,
} from "@/lib/database-access";

const ENGINES: { value: DatabaseEngine; label: string; port?: number }[] = [
  { value: "mysql", label: "MySQL", port: 3306 },
  { value: "mariadb", label: "MariaDB", port: 3306 },
  { value: "postgresql", label: "PostgreSQL", port: 5432 },
  { value: "sqlserver", label: "SQL Server", port: 1433 },
  { value: "oracle", label: "Oracle", port: 1521 },
  { value: "clickhouse", label: "ClickHouse", port: 8123 },
  { value: "sqlite", label: "SQLite" },
];
const ALL_DATA_SOURCE_CATEGORIES = "__all__";
const DEFAULT_DATA_SOURCE_CATEGORY = "本机电脑";

interface SourceFormState {
  name: string;
  category: string;
  engine: DatabaseEngine;
  description: string;
  host: string;
  port: string;
  username: string;
  password: string;
  serviceName: string;
  filePath: string;
  secure: boolean;
  verify: boolean;
  bootstrapDatabase: string;
  connectTimeoutSeconds: string;
  sendReceiveTimeoutSeconds: string;
  enabled: boolean;
}

const EMPTY_SOURCE: SourceFormState = {
  name: "",
  category: DEFAULT_DATA_SOURCE_CATEGORY,
  engine: "mysql",
  description: "",
  host: "127.0.0.1",
  port: "3306",
  username: "",
  password: "",
  serviceName: "",
  filePath: "",
  secure: false,
  verify: true,
  bootstrapDatabase: "default",
  connectTimeoutSeconds: "8",
  sendReceiveTimeoutSeconds: "15",
  enabled: true,
};

function engineLabel(engine: DatabaseEngine): string {
  return ENGINES.find((item) => item.value === engine)?.label ?? engine;
}

function endpoint(source: DataSourceSummary): string {
  if (source.engine === "sqlite") {
    return String(source.connection_config.file_path ?? "尚未配置文件路径");
  }
  const host = source.connection_config.host ?? "尚未配置主机";
  const port = source.connection_config.port;
  return port ? `${host}:${port}` : String(host);
}

function sourceForm(source?: DataSourceSummary): SourceFormState {
  if (!source) return { ...EMPTY_SOURCE };
  const clickHouseFields = clickHouseFieldsFromConfig(source.connection_config);
  return {
    name: source.name,
    category: source.category,
    engine: source.engine,
    description: source.description,
    host: String(source.connection_config.host ?? ""),
    port: String(source.connection_config.port ?? ""),
    username: String(source.connection_config.username ?? ""),
    password: "",
    serviceName: String(source.connection_config.service_name ?? ""),
    filePath: String(source.connection_config.file_path ?? ""),
    ...clickHouseFields,
    enabled: source.enabled,
  };
}

function sourcePayload(form: SourceFormState): DataSourcePayload {
  const connection_config: Record<string, string | number | boolean> = {};
  if (form.engine === "sqlite") {
    connection_config.file_path = form.filePath.trim();
  } else {
    connection_config.host = form.host.trim();
    if (form.port) connection_config.port = Number(form.port);
    connection_config.username = form.username.trim();
    if (form.password) connection_config.password = form.password;
    if (form.engine === "oracle" && form.serviceName) {
      connection_config.service_name = form.serviceName.trim();
    }
    if (form.engine === "clickhouse") {
      Object.assign(connection_config, clickHouseConfigFromFields(form));
    }
  }
  return {
    name: form.name.trim(),
    category: form.category.trim(),
    engine: form.engine,
    description: form.description.trim(),
    connection_config,
    enabled: form.enabled,
  };
}

export function DataSourceDashboard() {
  const [sources, setSources] = useState<DataSourceSummary[]>([]);
  const [engineCapabilities, setEngineCapabilities] = useState<
    DataSourceEngineCapability[]
  >([]);
  const [selectedCategory, setSelectedCategory] = useState(
    ALL_DATA_SOURCE_CATEGORIES,
  );
  const [selectedSource, setSelectedSource] = useState<DataSourceSummary | null>(null);
  const [databases, setDatabases] = useState<DataSourceDatabaseSummary[]>([]);
  const [sourceEditor, setSourceEditor] = useState<DataSourceSummary | "new" | null>(null);
  const [form, setForm] = useState<SourceFormState>({ ...EMPTY_SOURCE });
  const [showDatabaseForm, setShowDatabaseForm] = useState(false);
  const [databaseName, setDatabaseName] = useState("");
  const [databaseDisplayName, setDatabaseDisplayName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [revealingPassword, setRevealingPassword] = useState(false);
  const [syncingDatabases, setSyncingDatabases] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadSources = useCallback(async () => {
    const nextSources = await listDataSources();
    setSources(nextSources);
    setSelectedSource((current) =>
      current ? nextSources.find((item) => item.id === current.id) ?? null : current,
    );
  }, []);

  const loadDatabases = useCallback(async (source: DataSourceSummary) => {
    const nextDatabases = await listDataSourceDatabases(source.id);
    setDatabases(nextDatabases);
  }, []);

  useEffect(() => {
    void Promise.all([
      loadSources(),
      listDataSourceEngineCapabilities().then(setEngineCapabilities),
    ])
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "读取失败"))
      .finally(() => setLoading(false));
  }, [loadSources]);

  useEffect(() => {
    if (
      selectedCategory !== ALL_DATA_SOURCE_CATEGORIES &&
      !sources.some((source) => source.category === selectedCategory)
    ) {
      setSelectedCategory(ALL_DATA_SOURCE_CATEGORIES);
    }
  }, [selectedCategory, sources]);

  useEffect(() => {
    if (!selectedSource) {
      setDatabases([]);
      return;
    }
    void loadDatabases(selectedSource).catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "数据库清单读取失败"),
    );
  }, [loadDatabases, selectedSource]);

  function openSourceEditor(source?: DataSourceSummary) {
    setForm(sourceForm(source));
    setShowPassword(false);
    setSourceEditor(source ?? "new");
    setError(null);
    setNotice(null);
  }

  async function togglePasswordVisibility() {
    if (showPassword) {
      setShowPassword(false);
      return;
    }
    if (form.password || sourceEditor === "new" || !sourceEditor) {
      setShowPassword(true);
      return;
    }
    setRevealingPassword(true);
    setError(null);
    try {
      const result = await revealDataSourcePassword(sourceEditor.id);
      setForm((current) => ({ ...current, password: result.password }));
      setShowPassword(true);
      if (!result.password) setNotice("这个数据源没有保存密码。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "密码读取失败");
    } finally {
      setRevealingPassword(false);
    }
  }

  function changeEngine(engine: DatabaseEngine) {
    const port = ENGINES.find((item) => item.value === engine)?.port;
    setForm((current) => ({ ...current, engine, port: port ? String(port) : "" }));
  }

  async function submitSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sourceEditor) return;
    setBusy(true);
    setError(null);
    try {
      const saved = sourceEditor === "new"
        ? await createDataSource(sourcePayload(form))
        : await updateDataSource(sourceEditor.id, sourcePayload(form));
      await loadSources();
      setSelectedCategory(saved.category);
      setSelectedSource(saved);
      setSourceEditor(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "数据源保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function removeSource(source: DataSourceSummary) {
    if (!window.confirm(`删除数据源“${source.name}”及其库清单和项目关联？`)) return;
    setBusy(true);
    try {
      await deleteDataSource(source.id);
      if (selectedSource?.id === source.id) setSelectedSource(null);
      await loadSources();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "数据源删除失败");
    } finally {
      setBusy(false);
    }
  }

  async function testSourceConnection(source: DataSourceSummary) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await testDataSourceConnection(source.id);
      if (result.status === "passed") {
        setNotice(`${source.name} 连接成功（${result.duration_ms} ms）。`);
      } else {
        setError(`${result.message}${result.error_code ? `（${result.error_code}）` : ""}`);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "连接测试失败");
    } finally {
      setBusy(false);
    }
  }

  async function submitDatabase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedSource) return;
    setBusy(true);
    try {
      await createDataSourceDatabase(selectedSource.id, {
        remote_name: databaseName.trim(),
        display_name: databaseDisplayName.trim(),
        namespace_type: selectedSource.engine === "sqlite" ? "file" : "database",
        available: true,
        system_database: false,
        metadata: {},
      });
      setDatabaseName("");
      setDatabaseDisplayName("");
      setShowDatabaseForm(false);
      await Promise.all([loadDatabases(selectedSource), loadSources()]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "数据库添加失败");
    } finally {
      setBusy(false);
    }
  }

  async function removeDatabase(database: DataSourceDatabaseSummary) {
    if (!selectedSource || !window.confirm(`删除数据库“${database.remote_name}”及其项目关联？`)) return;
    setBusy(true);
    try {
      await deleteDataSourceDatabase(selectedSource.id, database.id);
      await Promise.all([loadDatabases(selectedSource), loadSources()]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "数据库删除失败");
    } finally {
      setBusy(false);
    }
  }

  async function syncSelectedSourceDatabases() {
    if (!selectedSource) return;
    setSyncingDatabases(true);
    setError(null);
    setNotice(null);
    try {
      const result = await syncDataSourceDatabases(selectedSource.id);
      setDatabases(result.databases);
      await loadSources();
      setNotice(
        `已从 ${selectedSource.name} 读取 ${result.discovered_count} 个可见数据库，新增 ${result.created_count} 个。`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "数据库同步失败");
    } finally {
      setSyncingDatabases(false);
    }
  }

  const categories = Array.from(
    new Set(sources.map((source) => source.category)),
  ).sort((left, right) => left.localeCompare(right, "zh-CN"));
  const visibleSources =
    selectedCategory === ALL_DATA_SOURCE_CATEGORIES
      ? sources
      : sources.filter((source) => source.category === selectedCategory);

  return (
    <>
      <nav
        className="data-source-category-tabs"
        role="tablist"
        aria-label="数据源分类"
      >
        <button
          type="button"
          role="tab"
          aria-selected={selectedCategory === ALL_DATA_SOURCE_CATEGORIES}
          data-active={selectedCategory === ALL_DATA_SOURCE_CATEGORIES}
          onClick={() => setSelectedCategory(ALL_DATA_SOURCE_CATEGORIES)}
        >
          <span>全部数据源</span>
          <small>{sources.length}</small>
        </button>
        {categories.map((category) => (
          <button
            type="button"
            role="tab"
            aria-selected={selectedCategory === category}
            data-active={selectedCategory === category}
            key={category}
            onClick={() => setSelectedCategory(category)}
          >
            <span>{category}</span>
            <small>
              {sources.filter((source) => source.category === category).length}
            </small>
          </button>
        ))}
      </nav>
      <div className="page-actions">
        <button type="button" className="primary-button" onClick={() => openSourceEditor()}>
          添加数据源
        </button>
      </div>
      {error ? <div className="error-banner" role="alert">{error}</div> : null}
      {notice ? <div className="success-banner" role="status">{notice}</div> : null}
      {loading ? <p className="empty-message">正在读取数据源…</p> : null}
      {!loading && sources.length === 0 ? (
        <div className="empty-state data-source-empty">
          <span className="empty-database-icon">◎</span>
          <h2>还没有数据源</h2>
          <p>先添加一个物理数据库连接，再维护这个连接下可供项目使用的库。</p>
          <button type="button" className="primary-button" onClick={() => openSourceEditor()}>
            添加第一个数据源
          </button>
        </div>
      ) : null}
      <section className="data-source-grid" aria-label="数据源列表">
        {visibleSources.map((source) => (
          <article className="data-source-card" data-enabled={source.enabled} key={source.id}>
            <header>
              <div>
                <div className="data-source-card-chips">
                  <span className="engine-chip">{engineLabel(source.engine)}</span>
                  <span className="data-source-category-chip">{source.category}</span>
                  <span className="data-source-category-chip">
                    {engineCapabilities.length === 0
                      ? "能力状态未加载"
                      : engineCapabilities.find((item) => item.engine === source.engine)
                            ?.queryable
                        ? "MCP 可查询"
                        : "仅配置管理，暂不支持 MCP 查询"}
                  </span>
                </div>
                <h2>{source.name}</h2>
              </div>
              <span className="project-status-chip" data-enabled={source.enabled}>
                {source.enabled ? "已启用" : "已停用"}
              </span>
            </header>
            <code className="source-endpoint">{endpoint(source)}</code>
            <p>{source.description || "暂无说明"}</p>
            <div className="source-stats">
              <span><strong>{source.database_count}</strong> 个库</span>
              <span><strong>{source.project_count}</strong> 个项目</span>
              <span>配置 v{source.config_version}</span>
            </div>
            <div className="data-source-actions">
              <button type="button" className="secondary-button" onClick={() => openSourceEditor(source)}>编辑连接</button>
              {supportsConnectionTest(
                engineCapabilities.find((item) => item.engine === source.engine),
              ) ? (
                <button type="button" className="secondary-button" disabled={busy} onClick={() => void testSourceConnection(source)}>测试连接</button>
              ) : null}
              <button type="button" className="secondary-button" onClick={() => setSelectedSource(source)}>管理数据库</button>
              <button type="button" className="danger-text-button" disabled={busy} onClick={() => void removeSource(source)}>删除</button>
            </div>
          </article>
        ))}
      </section>

      {sourceEditor ? (
        <div className="project-settings-modal" role="presentation">
          <form className="management-modal" role="dialog" aria-modal="true" onSubmit={submitSource}>
            <header>
              <div><span className="file-chip">物理连接</span><h2>{sourceEditor === "new" ? "添加数据源" : "编辑数据源"}</h2></div>
              <button type="button" className="close-button" aria-label="关闭" onClick={() => setSourceEditor(null)}>×</button>
            </header>
            <div className="management-form-grid">
              <label>数据源名称<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></label>
              <label>数据源分类<input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} placeholder="例如：自己服务器、公司内网服务器、本机电脑" maxLength={60} required /></label>
              <label>数据库类型<select value={form.engine} onChange={(e) => changeEngine(e.target.value as DatabaseEngine)}>{ENGINES.map((engine) => <option value={engine.value} key={engine.value}>{engine.label}</option>)}</select></label>
              {form.engine === "sqlite" ? (
                <label className="wide-field">SQLite 文件路径<input value={form.filePath} onChange={(e) => setForm({ ...form, filePath: e.target.value })} placeholder="/Users/name/data/app.db" required /></label>
              ) : (
                <>
                  <label>主机地址<input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} required /></label>
                  <label>端口<input type="number" value={form.port} onChange={(e) => setForm({ ...form, port: e.target.value })} required /></label>
                  <label>用户名<input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
                  <label>
                    密码
                    <span className="password-input-wrap">
                      <input
                        type={showPassword ? "text" : "password"}
                        value={form.password}
                        autoComplete="new-password"
                        onChange={(e) => setForm({ ...form, password: e.target.value })}
                        placeholder={
                          sourceEditor === "new"
                            ? "可留空"
                            : showPassword
                              ? "这个数据源没有保存密码"
                              : "已保存；点击眼睛查看，留空则保留"
                        }
                      />
                      <button
                        type="button"
                        className="password-visibility-button"
                        aria-label={showPassword ? "隐藏密码" : "显示明文密码"}
                        disabled={revealingPassword}
                        onClick={() => void togglePasswordVisibility()}
                      >
                        <svg aria-hidden="true" viewBox="0 0 24 24">
                          <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" />
                          <circle cx="12" cy="12" r="2.7" />
                          {showPassword ? <path d="m4 4 16 16" /> : null}
                        </svg>
                      </button>
                    </span>
                  </label>
                  {form.engine === "oracle" ? <label className="wide-field">Service Name<input value={form.serviceName} onChange={(e) => setForm({ ...form, serviceName: e.target.value })} /></label> : null}
                  {form.engine === "clickhouse" ? (
                    <>
                      <label>启动数据库<input value={form.bootstrapDatabase} onChange={(e) => setForm({ ...form, bootstrapDatabase: e.target.value })} placeholder="default" required /></label>
                      <label>连接超时（秒）<input type="number" min="1" max="60" value={form.connectTimeoutSeconds} onChange={(e) => setForm({ ...form, connectTimeoutSeconds: e.target.value })} required /></label>
                      <label>读写超时（秒）<input type="number" min="1" max="300" value={form.sendReceiveTimeoutSeconds} onChange={(e) => setForm({ ...form, sendReceiveTimeoutSeconds: e.target.value })} required /></label>
                      <label className="checkbox-field"><input type="checkbox" checked={form.secure} onChange={(e) => setForm({ ...form, secure: e.target.checked })} />使用 HTTPS/TLS</label>
                      <label className="checkbox-field"><input type="checkbox" checked={form.verify} onChange={(e) => setForm({ ...form, verify: e.target.checked })} />校验证书</label>
                      <p className="wide-field form-help">后端运行在 Docker 中；连接宿主机 ClickHouse 时请填写 host.docker.internal。</p>
                    </>
                  ) : null}
                </>
              )}
              <label className="wide-field">说明<textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="例如：订单系统本地开发库" /></label>
              <label className="checkbox-field wide-field"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />启用这个数据源</label>
            </div>
            <footer><button type="button" className="secondary-button" onClick={() => setSourceEditor(null)}>取消</button><button type="submit" className="primary-button" disabled={busy}>{busy ? "保存中…" : "保存数据源"}</button></footer>
          </form>
        </div>
      ) : null}

      {selectedSource ? (
        <div className="project-settings-modal source-detail-modal" role="presentation">
          <section className="source-detail-panel" role="dialog" aria-modal="true" aria-label={`${selectedSource.name} 数据库清单`}>
            <header>
              <div><span className="engine-chip">{engineLabel(selectedSource.engine)}</span><h2>{selectedSource.name}</h2><code>{endpoint(selectedSource)}</code></div>
              <button type="button" className="close-button" aria-label="关闭数据库管理" onClick={() => setSelectedSource(null)}>×</button>
            </header>
            <div className="source-detail-toolbar">
              <div><strong>数据库清单</strong><span>MySQL、MariaDB、PostgreSQL 和 ClickHouse 可从连接同步全部可见库，也可以继续手工维护。</span></div>
              <div className="source-detail-actions">
                {engineCapabilities.find((item) => item.engine === selectedSource.engine)?.discoverable ? (
                  <button type="button" className="secondary-button" disabled={syncingDatabases} onClick={() => void syncSelectedSourceDatabases()}>
                    {syncingDatabases ? "正在同步…" : "同步全部库"}
                  </button>
                ) : null}
                <button type="button" className="primary-button" onClick={() => setShowDatabaseForm((value) => !value)}>{showDatabaseForm ? "取消添加" : "添加数据库"}</button>
              </div>
            </div>
            {showDatabaseForm ? (
              <form className="inline-database-form" onSubmit={submitDatabase}>
                <label>实际库名<input value={databaseName} onChange={(e) => setDatabaseName(e.target.value)} required /></label>
                <label>展示名称<input value={databaseDisplayName} onChange={(e) => setDatabaseDisplayName(e.target.value)} placeholder="可留空" /></label>
                <button type="submit" className="primary-button" disabled={busy}>确认添加</button>
              </form>
            ) : null}
            <div className="database-list">
              {databases.length === 0 ? <p className="empty-message">这个连接下还没有维护数据库。</p> : null}
              {databases.map((database) => {
                return (
                  <article className="database-row" key={database.id}>
                    <div className="database-row-main">
                      <span className="database-symbol">DB</span>
                      <div><h3>{database.display_name || database.remote_name}</h3><code>{database.remote_name}</code></div>
                      <span className="node-count">{database.project_count} 个项目</span>
                      {database.system_database ? <span className="database-kind-chip">系统库</span> : null}
                      {!database.available ? <span className="database-kind-chip" data-status="unavailable">本次未发现</span> : null}
                    </div>
                    <span className="database-project-summary">
                      项目关联请在项目管理中配置
                    </span>
                    <button type="button" className="danger-text-button" onClick={() => void removeDatabase(database)}>删除库</button>
                  </article>
                );
              })}
            </div>
          </section>
        </div>
      ) : null}

    </>
  );
}
