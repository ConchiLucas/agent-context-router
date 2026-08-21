"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  listDataSourceDatabases,
  listDataSourceEngineCapabilities,
  listDataSources,
  revealDataSourcePassword,
  testDataSourceConnection,
} from "@/lib/api";
import type {
  DatabaseEngine,
  DataSourceDatabaseSummary,
  DataSourceEngineCapability,
  DataSourceSummary,
} from "@/lib/types";
import { supportsConnectionTest } from "@/lib/database-access";

const ENGINES: { value: DatabaseEngine; label: string }[] = [
  { value: "mysql", label: "MySQL" },
  { value: "mariadb", label: "MariaDB" },
  { value: "doris", label: "Apache Doris" },
  { value: "postgresql", label: "PostgreSQL" },
  { value: "sqlserver", label: "SQL Server" },
  { value: "oracle", label: "Oracle" },
  { value: "clickhouse", label: "ClickHouse" },
  { value: "sqlite", label: "SQLite" },
];
const ALL_DATA_SOURCE_CATEGORIES = "__all__";

const CONFIG_LABELS: Record<string, string> = {
  host: "主机地址",
  port: "端口",
  username: "用户名",
  database: "默认数据库",
  dbname: "默认数据库",
  service_name: "Service Name",
  file_path: "SQLite 文件路径",
  bootstrap_database: "启动数据库",
  secure: "HTTPS / TLS",
  verify: "证书校验",
  connect_timeout_seconds: "连接超时（秒）",
  send_receive_timeout_seconds: "读写超时（秒）",
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

function displayConfigValue(value: string | number | boolean): string {
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("zh-CN", { hour12: false });
}

export function DataSourceDashboard() {
  const [sources, setSources] = useState<DataSourceSummary[]>([]);
  const [engineCapabilities, setEngineCapabilities] = useState<
    DataSourceEngineCapability[]
  >([]);
  const [selectedCategory, setSelectedCategory] = useState(
    ALL_DATA_SOURCE_CATEGORIES,
  );
  const [connectionSource, setConnectionSource] =
    useState<DataSourceSummary | null>(null);
  const [selectedSource, setSelectedSource] =
    useState<DataSourceSummary | null>(null);
  const [databases, setDatabases] = useState<DataSourceDatabaseSummary[]>([]);
  const [revealedPassword, setRevealedPassword] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(true);
  const [databaseLoading, setDatabaseLoading] = useState(false);
  const [revealingPassword, setRevealingPassword] = useState(false);
  const [testingSourceId, setTestingSourceId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const databaseRequestRef = useRef(0);
  const passwordRequestRef = useRef(0);

  const loadSources = useCallback(async () => {
    const nextSources = await listDataSources();
    setSources(nextSources);
    setConnectionSource((current) =>
      current
        ? nextSources.find((item) => item.id === current.id) ?? null
        : current,
    );
    setSelectedSource((current) =>
      current
        ? nextSources.find((item) => item.id === current.id) ?? null
        : current,
    );
  }, []);

  useEffect(() => {
    void Promise.all([
      loadSources(),
      listDataSourceEngineCapabilities().then(setEngineCapabilities),
    ])
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : "读取失败"),
      )
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
    const requestId = ++databaseRequestRef.current;
    if (!selectedSource) {
      setDatabases([]);
      setDatabaseLoading(false);
      return;
    }

    setDatabases([]);
    setDatabaseLoading(true);
    void listDataSourceDatabases(selectedSource.id)
      .then((nextDatabases) => {
        if (databaseRequestRef.current === requestId) {
          setDatabases(nextDatabases);
        }
      })
      .catch((reason: unknown) => {
        if (databaseRequestRef.current === requestId) {
          setError(
            reason instanceof Error ? reason.message : "数据库清单读取失败",
          );
        }
      })
      .finally(() => {
        if (databaseRequestRef.current === requestId) {
          setDatabaseLoading(false);
        }
      });
  }, [selectedSource]);

  const connectionEntries = useMemo(() => {
    if (!connectionSource) return [];
    const preferredOrder = Object.keys(CONFIG_LABELS);
    return Object.entries(connectionSource.connection_config).sort(
      ([left], [right]) => {
        const leftIndex = preferredOrder.indexOf(left);
        const rightIndex = preferredOrder.indexOf(right);
        if (leftIndex === -1 && rightIndex === -1) {
          return left.localeCompare(right);
        }
        if (leftIndex === -1) return 1;
        if (rightIndex === -1) return -1;
        return leftIndex - rightIndex;
      },
    );
  }, [connectionSource]);

  const categories = Array.from(
    new Set(sources.map((source) => source.category)),
  ).sort((left, right) => left.localeCompare(right, "zh-CN"));
  const visibleSources =
    selectedCategory === ALL_DATA_SOURCE_CATEGORIES
      ? sources
      : sources.filter((source) => source.category === selectedCategory);

  function openConnectionDetails(source: DataSourceSummary) {
    passwordRequestRef.current += 1;
    setConnectionSource(source);
    setRevealedPassword(null);
    setShowPassword(false);
    setRevealingPassword(false);
    setError(null);
    setNotice(null);
  }

  function closeConnectionDetails() {
    passwordRequestRef.current += 1;
    setConnectionSource(null);
    setRevealedPassword(null);
    setShowPassword(false);
    setRevealingPassword(false);
  }

  function openDatabases(source: DataSourceSummary) {
    databaseRequestRef.current += 1;
    setDatabases([]);
    setDatabaseLoading(true);
    setSelectedSource(source);
    setError(null);
  }

  function closeDatabases() {
    databaseRequestRef.current += 1;
    setSelectedSource(null);
    setDatabases([]);
    setDatabaseLoading(false);
  }

  async function togglePasswordVisibility() {
    if (!connectionSource) return;
    if (showPassword) {
      setShowPassword(false);
      return;
    }
    if (revealedPassword !== null) {
      setShowPassword(true);
      return;
    }

    setRevealingPassword(true);
    setError(null);
    const requestId = ++passwordRequestRef.current;
    try {
      const result = await revealDataSourcePassword(connectionSource.id);
      if (passwordRequestRef.current !== requestId) return;
      setRevealedPassword(result.password);
      setShowPassword(true);
      if (!result.password) setNotice("这个数据源没有保存密码。");
    } catch (reason) {
      if (passwordRequestRef.current === requestId) {
        setError(reason instanceof Error ? reason.message : "密码读取失败");
      }
    } finally {
      if (passwordRequestRef.current === requestId) {
        setRevealingPassword(false);
      }
    }
  }

  async function testSourceConnection(source: DataSourceSummary) {
    setTestingSourceId(source.id);
    setError(null);
    setNotice(null);
    try {
      const result = await testDataSourceConnection(source.id);
      if (result.status === "passed") {
        setNotice(`${source.name} 连接成功（${result.duration_ms} ms）。`);
      } else {
        setError(
          `${result.message}${result.error_code ? `（${result.error_code}）` : ""}`,
        );
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "连接测试失败");
    } finally {
      setTestingSourceId(null);
    }
  }

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

      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="success-banner" role="status">
          {notice}
        </div>
      ) : null}
      {loading ? <p className="empty-message">正在读取数据源…</p> : null}
      {!loading && sources.length === 0 ? (
        <div className="empty-state data-source-empty">
          <span className="empty-database-icon">◎</span>
          <h2>还没有数据源</h2>
          <p>
            当前页面只负责查看。需要增加连接时，请让 AI 通过受控的运维入口维护。
          </p>
        </div>
      ) : null}

      <section className="data-source-grid" aria-label="数据源列表">
        {visibleSources.map((source) => {
          const capability = engineCapabilities.find(
            (item) => item.engine === source.engine,
          );
          return (
            <article className="data-source-card" key={source.id}>
              <header>
                <div>
                  <div className="data-source-card-chips">
                    <span className="engine-chip">
                      {engineLabel(source.engine)}
                    </span>
                    <span className="data-source-category-chip">
                      {source.category}
                    </span>
                    <span className="data-source-category-chip">
                      {engineCapabilities.length === 0
                        ? "能力状态未加载"
                        : capability?.queryable
                          ? "MCP 可查询"
                          : "暂不支持 MCP 查询"}
                    </span>
                  </div>
                  <h2>{source.name}</h2>
                </div>
              </header>
              <code className="source-endpoint">{endpoint(source)}</code>
              <p>{source.description || "暂无说明"}</p>
              <div className="source-stats">
                <span>
                  <strong>{source.database_count}</strong> 个库
                </span>
                <span>
                  <strong>{source.project_count}</strong> 个项目
                </span>
                <span>配置 v{source.config_version}</span>
              </div>
              <div className="data-source-actions">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => openConnectionDetails(source)}
                >
                  查看连接
                </button>
                {supportsConnectionTest(capability) ? (
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={testingSourceId !== null}
                    onClick={() => void testSourceConnection(source)}
                  >
                    {testingSourceId === source.id
                      ? "正在测试…"
                      : "测试连接"}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => openDatabases(source)}
                >
                  查看数据库
                </button>
              </div>
            </article>
          );
        })}
      </section>

      {connectionSource ? (
        <div className="project-settings-modal" role="presentation">
          <section
            className="management-modal"
            role="dialog"
            aria-modal="true"
            aria-label={`${connectionSource.name} 连接详情`}
          >
            <header>
              <div>
                <span className="file-chip">只读连接</span>
                <h2>查看连接</h2>
              </div>
              <button
                type="button"
                className="close-button"
                aria-label="关闭连接详情"
                onClick={closeConnectionDetails}
              >
                ×
              </button>
            </header>

            <div className="source-stats">
              <span>{engineLabel(connectionSource.engine)}</span>
              <span>{connectionSource.category}</span>
              <span>配置 v{connectionSource.config_version}</span>
            </div>

            <dl className="trace-detail-facts">
              <div>
                <dt>名称</dt>
                <dd>{connectionSource.name}</dd>
              </div>
              <div>
                <dt>说明</dt>
                <dd>{connectionSource.description || "暂无说明"}</dd>
              </div>
              {connectionEntries.map(([key, value]) => (
                <div key={key}>
                  <dt>{CONFIG_LABELS[key] ?? key}</dt>
                  <dd>
                    <code>{displayConfigValue(value)}</code>
                  </dd>
                </div>
              ))}
              {connectionSource.engine !== "sqlite" ? (
                <div>
                  <dt>密码</dt>
                  <dd>
                    <code>
                      {showPassword
                        ? revealedPassword || "未保存"
                        : "••••••••"}
                    </code>{" "}
                    <button
                      type="button"
                      className="text-button"
                      disabled={revealingPassword}
                      onClick={() => void togglePasswordVisibility()}
                    >
                      {revealingPassword
                        ? "读取中…"
                        : showPassword
                          ? "隐藏"
                          : "查看密码"}
                    </button>
                  </dd>
                </div>
              ) : null}
              <div>
                <dt>创建时间</dt>
                <dd>{formatTimestamp(connectionSource.created_at)}</dd>
              </div>
              <div>
                <dt>更新时间</dt>
                <dd>{formatTimestamp(connectionSource.updated_at)}</dd>
              </div>
            </dl>

            <footer>
              {supportsConnectionTest(
                engineCapabilities.find(
                  (item) => item.engine === connectionSource.engine,
                ),
              ) ? (
                <button
                  type="button"
                  className="secondary-button"
                  disabled={testingSourceId !== null}
                  onClick={() => void testSourceConnection(connectionSource)}
                >
                  {testingSourceId === connectionSource.id
                    ? "正在测试…"
                    : "测试连接"}
                </button>
              ) : null}
              <button
                type="button"
                className="primary-button"
                onClick={closeConnectionDetails}
              >
                关闭
              </button>
            </footer>
          </section>
        </div>
      ) : null}

      {selectedSource ? (
        <div
          className="project-settings-modal source-detail-modal"
          role="presentation"
        >
          <section
            className="source-detail-panel"
            role="dialog"
            aria-modal="true"
            aria-label={`${selectedSource.name} 数据库清单`}
          >
            <header>
              <div>
                <span className="engine-chip">
                  {engineLabel(selectedSource.engine)}
                </span>
                <h2>{selectedSource.name}</h2>
                <code>{endpoint(selectedSource)}</code>
              </div>
              <button
                type="button"
                className="close-button"
                aria-label="关闭数据库清单"
                onClick={closeDatabases}
              >
                ×
              </button>
            </header>
            <div className="source-detail-toolbar">
              <div>
                <strong>数据库清单</strong>
                <span>
                  只读展示当前已登记的数据库；同步、增加、删除由 AI
                  通过受控运维入口完成。
                </span>
              </div>
              <div className="source-detail-actions">
                <span>
                  {databaseLoading
                    ? "正在读取…"
                    : `${databases.length} 个数据库`}
                </span>
              </div>
            </div>
            <div className="database-list">
              {databaseLoading ? (
                <p className="empty-message">正在读取数据库清单…</p>
              ) : null}
              {!databaseLoading && databases.length === 0 ? (
                <p className="empty-message">
                  这个连接下还没有登记数据库。
                </p>
              ) : null}
              {databases.map((database) => (
                <article className="database-row" key={database.id}>
                  <div className="database-row-main">
                    <span className="database-symbol">DB</span>
                    <div>
                      <h3>
                        {database.display_name || database.remote_name}
                      </h3>
                      <code>{database.remote_name}</code>
                    </div>
                    <span className="node-count">
                      {database.project_count} 个项目
                    </span>
                  </div>
                  <span className="database-project-summary">
                    命名空间：{database.namespace_type}
                  </span>
                  <div className="database-project-links">
                    {database.system_database ? (
                      <span className="database-kind-chip">系统库</span>
                    ) : null}
                    <span
                      className="database-kind-chip"
                      data-status={
                        database.available ? undefined : "unavailable"
                      }
                    >
                      {database.available ? "可用" : "本次未发现"}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
