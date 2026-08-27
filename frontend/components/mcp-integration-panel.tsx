"use client";

import { useEffect, useState } from "react";

import { getMcpIntegration, runMcpIntegrationTest } from "@/lib/api";
import type {
  McpClientConfig,
  McpIntegrationInfo,
  McpIntegrationTestResult,
  WorkspaceSummary,
} from "@/lib/types";

type IntegrationTab =
  | "connection"
  | "codex"
  | "gemini"
  | "antigravity"
  | "cursor"
  | "grok"
  | "test";

interface McpIntegrationPanelProps {
  workspace: WorkspaceSummary;
  onClose: () => void;
}

const tabs: Array<{ id: IntegrationTab; label: string }> = [
  { id: "connection", label: "连接信息" },
  { id: "codex", label: "Codex" },
  { id: "gemini", label: "Gemini" },
  { id: "antigravity", label: "Antigravity" },
  { id: "cursor", label: "Cursor" },
  { id: "grok", label: "Grok" },
  { id: "test", label: "连接测试" },
];

function ClientConfigGuide({
  client,
  copied,
  onCopy,
}: {
  client: McpClientConfig | undefined;
  copied: boolean;
  onCopy: (value: string, key: string) => void;
}) {
  if (!client) return <p className="empty-message">配置模板尚未加载。</p>;
  const isCommand = client.setup_kind === "command";

  return (
    <section className="integration-guide">
      <div className="integration-guide-copy">
        <span className="file-chip">{client.title}</span>
        <h3>{isCommand ? "运行 MCP 配置命令" : "添加一个全局 MCP 服务"}</h3>
        <p>
          全局配置文件：<code>{client.config_path}</code>
        </p>
        {client.project_config_path ? (
          <p>
            也可以仅对当前工作空间配置：<code>{client.project_config_path}</code>
          </p>
        ) : null}
      </div>
      <div className="integration-code-block">
        <button
          type="button"
          className="secondary-button integration-copy-button"
          onClick={() => onCopy(client.config, `${client.client}-config`)}
        >
          {copied ? "已复制" : isCommand ? "复制命令" : "复制配置"}
        </button>
        <pre>
          <code>{client.config}</code>
        </pre>
      </div>
      <div className="integration-note">
        <strong>接入后怎么用</strong>
        <p>
          新任务先调用 <code>prepare_task_context</code> 获取 task_id 和文档导航。
          文档链路直接调用 <code>search_context_documents</code> 和
          <code> read_context_document</code>；数据库、接口、日志和映射等专业能力优先复用
          recommended_actions，缺少动作时再执行
          <code> discover_task_tools → invoke_task_tool</code>。
          没有匹配工作空间时，客户端继续使用普通源码检索。
        </p>
      </div>
    </section>
  );
}

export function McpIntegrationPanel({
  workspace,
  onClose,
}: McpIntegrationPanelProps) {
  const [tab, setTab] = useState<IntegrationTab>("connection");
  const [info, setInfo] = useState<McpIntegrationInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] =
    useState<McpIntegrationTestResult | null>(null);

  useEffect(() => {
    let active = true;
    void getMcpIntegration()
      .then((result) => {
        if (!active) return;
        setInfo(result);
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
  }, []);

  async function copy(value: string, key: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedKey(key);
      window.setTimeout(() => setCopiedKey(null), 1800);
    } catch {
      setError("浏览器未允许写入剪贴板，请手动复制配置");
    }
  }

  async function runTest() {
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await runMcpIntegrationTest(workspace.id));
      setError(null);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setTesting(false);
    }
  }

  const codex = info?.clients.find((client) => client.client === "codex");
  const gemini = info?.clients.find((client) => client.client === "gemini");
  const antigravity = info?.clients.find(
    (client) => client.client === "antigravity",
  );
  const cursor = info?.clients.find((client) => client.client === "cursor");
  const grok = info?.clients.find((client) => client.client === "grok");
  const databaseToolsAvailable = Boolean(
    info?.tools.some((tool) => tool.name === "search_database_objects") &&
      info.tools.some((tool) => tool.name === "execute_database_query"),
  );

  return (
    <div className="mcp-integration-modal" role="presentation">
      <section
        className="mcp-integration-panel"
        role="dialog"
        aria-modal="true"
        aria-label="MCP 接入与测试"
        data-workspace-detail-subdialog
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }}
      >
        <header className="mcp-integration-header">
          <div>
            <span className="file-chip">Streamable HTTP</span>
            <h2>MCP 接入与测试</h2>
            <p>复制客户端配置，并从当前服务验证文档与数据库上下文能力。</p>
          </div>
          <button
            type="button"
            className="close-button"
            aria-label="关闭 MCP 接入面板"
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <nav className="mcp-integration-tabs" role="tablist" aria-label="MCP 接入步骤">
          {tabs.map((item) => (
            <button
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              data-active={tab === item.id}
              key={item.id}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="mcp-integration-content">
          {loading ? <p className="empty-message">正在读取接入信息…</p> : null}
          {error ? (
            <div className="error-banner" role="alert">
              {error}
            </div>
          ) : null}

          {!loading && info && tab === "connection" ? (
            <div className="integration-connection">
              <section className="integration-endpoint">
                <div>
                  <span>MCP 服务地址</span>
                  <strong>{info.service.url}</strong>
                  <small>
                    {info.service.name} · {info.service.transport}
                  </small>
                </div>
                <button
                  type="button"
                  className="primary-button"
                  onClick={() => copy(info.service.url, "service-url")}
                >
                  {copiedKey === "service-url" ? "已复制" : "复制地址"}
                </button>
              </section>

              <section className="integration-readiness" aria-label="服务就绪状态">
                <article data-ready="true">
                  <span>传输协议</span>
                  <strong>{info.service.transport}</strong>
                </article>
                <article data-ready={info.readiness.database_configured}>
                  <span>任务数据库</span>
                  <strong>
                    {info.readiness.database_configured ? "已配置" : "未配置"}
                  </strong>
                </article>
                <article data-ready={info.readiness.workspace_count > 0}>
                  <span>可匹配工作空间</span>
                  <strong>{info.readiness.workspace_count} 个</strong>
                </article>
                <article data-ready={databaseToolsAvailable}>
                  <span>数据库工具</span>
                  <strong>{databaseToolsAvailable ? "已注册" : "未注册"}</strong>
                </article>
              </section>

              <section className="integration-tools">
                <div>
                  <span className="file-chip">可用工具</span>
                  <h3>客户端接入后会发现以下能力</h3>
                </div>
                {info.tools.map((tool, index) => (
                  <article key={tool.name}>
                    <span>{index + 1}</span>
                    <div>
                      <code>{tool.name}</code>
                      <p>{tool.description}</p>
                    </div>
                  </article>
                ))}
                <div className="integration-note">
                  <strong>核心工具与专业动作</strong>
                  <p>
                    prepare、文档搜索和文档读取是核心直连工具，不经过统一调用入口；
                    discover 只返回专业动作，invoke 必须复制动作的 tool_name 和
                    definition_revision。数据库目标统一由当前 task 解析，客户端不传数据库别名。
                  </p>
                </div>
              </section>
            </div>
          ) : null}

          {!loading && info && tab === "codex" ? (
            <ClientConfigGuide
              client={codex}
              copied={copiedKey === "codex-config"}
              onCopy={copy}
            />
          ) : null}

          {!loading && info && tab === "gemini" ? (
            <ClientConfigGuide
              client={gemini}
              copied={copiedKey === "gemini-config"}
              onCopy={copy}
            />
          ) : null}

          {!loading && info && tab === "antigravity" ? (
            <ClientConfigGuide
              client={antigravity}
              copied={copiedKey === "antigravity-config"}
              onCopy={copy}
            />
          ) : null}

          {!loading && info && tab === "cursor" ? (
            <ClientConfigGuide
              client={cursor}
              copied={copiedKey === "cursor-config"}
              onCopy={copy}
            />
          ) : null}

          {!loading && info && tab === "grok" ? (
            <ClientConfigGuide
              client={grok}
              copied={copiedKey === "grok-config"}
              onCopy={copy}
            />
          ) : null}

          {!loading && info && tab === "test" ? (
            <div className="integration-test">
              <section className="integration-test-controls">
                <div>
                  <span className="file-chip">端到端验证</span>
                  <h3>对当前工作空间执行真实 MCP 调用</h3>
                  <p>
                    测试会创建一条隐藏的 connection-test 任务，验证核心文档链路以及
                    discover → invoke 专业动作链路；不会执行任何业务数据库查询。
                  </p>
                </div>
                <div className="integration-test-workspace">
                  <span>测试工作空间</span>
                  <strong>{workspace.name}</strong>
                  <code>{workspace.root_path}</code>
                </div>
                <button
                  type="button"
                  className="primary-button"
                  disabled={testing || !info.readiness.ready_for_full_test}
                  onClick={() => void runTest()}
                >
                  {testing ? "正在执行完整链路…" : "开始连接测试"}
                </button>
              </section>

              {!info.readiness.ready_for_full_test ? (
                <div className="integration-note integration-warning">
                  <strong>暂时不能执行完整测试</strong>
                  <p>
                    {!info.readiness.database_configured
                      ? "请先配置 PostgreSQL 任务数据库。"
                      : "请先添加至少一个工作空间。"}
                  </p>
                </div>
              ) : null}

              {testResult ? (
                <section className="integration-test-result" data-status={testResult.status}>
                  <header>
                    <div>
                      <span>
                        {testResult.status === "passed" ? "测试通过" : "测试未通过"}
                      </span>
                      <h3>{testResult.workspace_name ?? "MCP 接入测试"}</h3>
                    </div>
                    {testResult.task_id ? (
                      <code>
                        task #{testResult.task_id}
                        {testResult.read_call_id
                          ? ` · read #${testResult.read_call_id}`
                          : ""}
                      </code>
                    ) : null}
                  </header>
                  <ol>
                    {testResult.stages.map((stage) => (
                      <li data-status={stage.status} key={stage.key}>
                        <span aria-hidden="true" />
                        <div>
                          <strong>{stage.label}</strong>
                          <p>{stage.detail}</p>
                        </div>
                        <small>{stage.duration_ms} ms</small>
                      </li>
                    ))}
                  </ol>
                </section>
              ) : null}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
