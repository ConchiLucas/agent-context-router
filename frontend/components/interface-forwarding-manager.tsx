"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  deleteInterfaceForwardingInterface,
  deleteInterfaceForwardingService,
  executeInterfaceForwarding,
  getInterfaceForwardingOverview,
  getInterfaceForwardingState,
  importInterfaceForwardingSpec,
  listInterfaceForwardingIdentities,
  listInterfaceForwardingLogs,
  listWorkspaces,
  renameInterfaceForwardingService,
} from "@/lib/api";
import { groupInterfaceForwardingIdentities } from "@/lib/interface-forwarding-identities";
import { sortInterfacesByLastRequest } from "@/lib/interface-forwarding-order";
import type {
  InterfaceForwardingEnvironment,
  InterfaceForwardingIdentity,
  InterfaceForwardingInterface,
  InterfaceForwardingLog,
  InterfaceForwardingOverview,
  WorkspaceSummary,
} from "@/lib/types";

type Modal =
  | { kind: "import" }
  | { kind: "configuration" }
  | { kind: "detail"; item: InterfaceForwardingInterface }
  | { kind: "test"; item: InterfaceForwardingInterface }
  | null;

function methodClass(method: string) {
  return `interface-forwarding-method interface-forwarding-method--${method.toLowerCase()}`;
}

function formatRequestedAt(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function ModalFrame({ title, children, onClose, wide = false }: { title: string; children: React.ReactNode; onClose: () => void; wide?: boolean }) {
  return (
    <div className="interface-forwarding-overlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className={`management-modal interface-forwarding-modal${wide ? " interface-forwarding-modal--wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <header><div><p className="eyebrow">INTERFACE FORWARDING</p><h2>{title}</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="关闭">×</button></header>
        {children}
      </section>
    </div>
  );
}

export function InterfaceForwardingManager() {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [overview, setOverview] = useState<InterfaceForwardingOverview | null>(null);
  const [activeServiceId, setActiveServiceId] = useState<string>("");
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState<Modal>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listWorkspaces().then((items) => {
      setWorkspaces(items);
      setWorkspaceId((current) => current || items[0]?.id || "");
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  const load = useCallback(async (nextKeyword = keyword) => {
    if (!workspaceId) return;
    setLoading(true);
    setError("");
    try {
      const result = await getInterfaceForwardingOverview(workspaceId, nextKeyword);
      setOverview(result);
      setActiveServiceId((current) => result.services.some((item) => item.id === current) ? current : result.services[0]?.id || "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "接口转发数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [keyword, workspaceId]);

  useEffect(() => { void load(""); }, [workspaceId]); // eslint-disable-line react-hooks/exhaustive-deps

  const visibleInterfaces = useMemo(() => {
    if (!overview) return [];
    const items = activeServiceId
      ? overview.services.find((service) => service.id === activeServiceId)?.interfaces ?? []
      : overview.services.flatMap((service) => service.interfaces);
    return sortInterfacesByLastRequest(items);
  }, [activeServiceId, overview]);

  async function destructive(message: string, action: () => Promise<void>) {
    if (!window.confirm(message)) return;
    setBusy(true);
    setError("");
    try { await action(); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败"); } finally { setBusy(false); }
  }

  async function renameService(serviceId: string, oldName: string) {
    const name = window.prompt("请输入新的服务名称", oldName)?.trim();
    if (!name || name === oldName) return;
    setBusy(true);
    try { await renameInterfaceForwardingService(serviceId, name); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "重命名失败"); } finally { setBusy(false); }
  }

  return (
    <section className="interface-forwarding-page">
      <header className="interface-forwarding-heading">
        <div><p className="eyebrow">INTERFACE FORWARDING</p><h1>接口转发</h1><p>管理接口文档、转发环境和请求身份，并直接测试已登记接口。</p></div>
        <label>工作空间<select value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)}>{workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}</select></label>
      </header>

      <div className="interface-forwarding-toolbar">
        <div className="interface-forwarding-search"><input value={keyword} onChange={(event) => setKeyword(event.target.value)} onKeyDown={(event) => event.key === "Enter" && void load()} placeholder="搜索接口、路径或 Controller" /><button className="secondary-button" type="button" onClick={() => void load()}>搜索</button></div>
        <div><button className="secondary-button" type="button" onClick={() => setModal({ kind: "configuration" })}>转发配置</button><button className="primary-button" type="button" onClick={() => setModal({ kind: "import" })}>导入 Swagger</button></div>
      </div>
      {error ? <p className="error-banner" role="alert">{error}</p> : null}

      <div className="interface-forwarding-layout">
        <aside className="interface-forwarding-services">
          <header><strong>接口服务</strong><span>{overview?.services.length ?? 0}</span></header>
          <button type="button" data-active={!activeServiceId} onClick={() => setActiveServiceId("")}><span>全部接口</span><small>{overview?.services.reduce((sum, item) => sum + item.interface_count, 0) ?? 0}</small></button>
          {overview?.services.map((service) => (
            <div className="interface-forwarding-service-row" key={service.id} data-active={activeServiceId === service.id}>
              <button type="button" onClick={() => setActiveServiceId(service.id)}><span>{service.name}</span><small>{service.interface_count}</small></button>
              <div><button type="button" title="重命名" onClick={() => void renameService(service.id, service.name)}>✎</button><button type="button" title="删除" disabled={busy} onClick={() => void destructive(`确定删除服务“${service.name}”及其全部接口、参数和日志吗？`, () => deleteInterfaceForwardingService(service.id))}>×</button></div>
            </div>
          ))}
        </aside>

        <section className="interface-forwarding-list">
          <header><div><h2>{activeServiceId ? overview?.services.find((item) => item.id === activeServiceId)?.name : "全部接口"}</h2><p>{visibleInterfaces.length} 个接口</p></div></header>
          {loading ? <div className="interface-forwarding-empty">正在加载接口…</div> : null}
          {!loading && visibleInterfaces.length === 0 ? <div className="interface-forwarding-empty"><strong>还没有接口</strong><p>导入 Swagger 2 或 OpenAPI 3 JSON 后会在这里建立服务树和接口列表。</p></div> : null}
          {!loading && visibleInterfaces.length > 0 ? (
            <div className="interface-forwarding-table-wrap"><table><colgroup><col className="interface-forwarding-col-name" /><col className="interface-forwarding-col-controller" /><col className="interface-forwarding-col-path" /><col className="interface-forwarding-col-action" /></colgroup><thead><tr><th>接口名称</th><th>Controller 名称</th><th>接口路径</th><th>操作</th></tr></thead><tbody>{visibleInterfaces.map((item) => (
              <tr key={item.id}><td><div className="interface-forwarding-name-cell"><button className="interface-forwarding-name-button" type="button" title={item.name} onClick={() => setModal({ kind: "detail", item })}>{item.name}</button>{item.last_requested_at ? <span className="interface-forwarding-requested-badge" title={`最近请求：${formatRequestedAt(item.last_requested_at)}`} aria-label={`已请求，最近请求时间 ${formatRequestedAt(item.last_requested_at)}`}>已请求</span> : null}</div></td><td><code className="interface-forwarding-cell-ellipsis" title={item.controller_name || "未提供 Controller 名称"}>{item.controller_name || "—"}</code></td><td><div className="interface-forwarding-path-cell" tabIndex={0} aria-label={`${item.method} ${item.path}`} data-full-path={item.path}><span className={methodClass(item.method)}>{item.method}</span><code>{item.path}</code></div></td><td><div className="interface-forwarding-row-actions"><button className="interface-forwarding-row-detail" type="button" onClick={() => setModal({ kind: "test", item })}>测试</button><button className="interface-forwarding-row-detail" type="button" onClick={() => setModal({ kind: "detail", item })}>详情</button></div></td></tr>
            ))}</tbody></table></div>
          ) : null}
        </section>
      </div>

      {modal?.kind === "import" ? <ImportModal workspaceId={workspaceId} onClose={() => setModal(null)} onImported={async () => { setModal(null); await load(); }} /> : null}
      {modal?.kind === "configuration" && overview ? <ForwardingConfigurationModal workspaceId={workspaceId} environments={overview.environments} onClose={() => setModal(null)} /> : null}
      {modal?.kind === "detail" && overview ? <InterfaceDetailModal item={modal.item} onClose={() => setModal(null)} onDelete={() => destructive(`确定删除接口“${modal.item.name}”及其参数和日志吗？`, async () => { await deleteInterfaceForwardingInterface(modal.item.id); setModal(null); })} /> : null}
      {modal?.kind === "test" && overview ? <TestModal item={modal.item} environments={overview.environments} onClose={() => { setModal(null); void load(); }} /> : null}
    </section>
  );
}

function ImportModal({ workspaceId, onClose, onImported }: { workspaceId: string; onClose: () => void; onImported: () => Promise<void> }) {
  const [name, setName] = useState(""); const [file, setFile] = useState<File | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function submit() {
    if (!file || !name.trim()) { setError("请输入服务名称并选择 JSON 文件"); return; }
    setBusy(true); setError("");
    try { const parsed = JSON.parse(await file.text()) as Record<string, unknown>; await importInterfaceForwardingSpec({ workspace_id: workspaceId, service_name: name.trim(), spec: parsed }); await onImported(); } catch (reason) { setError(reason instanceof Error ? reason.message : "导入失败"); } finally { setBusy(false); }
  }
  return <ModalFrame title="导入 Swagger / OpenAPI" onClose={onClose}><div className="management-form-grid"><label className="wide-field">服务名称<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：订单服务" /></label><label className="wide-field">JSON 文件<input type="file" accept="application/json,.json" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label></div>{error ? <p className="error-banner">{error}</p> : null}<footer><button className="secondary-button" type="button" onClick={onClose}>取消</button><button className="primary-button" type="button" disabled={busy} onClick={() => void submit()}>{busy ? "导入中…" : "开始导入"}</button></footer></ModalFrame>;
}

function ForwardingConfigurationModal({ workspaceId, environments, onClose }: { workspaceId: string; environments: InterfaceForwardingEnvironment[]; onClose: () => void }) {
  const [environmentKey, setEnvironmentKey] = useState(environments[0]?.environment_key || "");
  const [items, setItems] = useState<InterfaceForwardingIdentity[]>([]);
  const [error, setError] = useState("");
  const environment = environments.find((item) => item.environment_key === environmentKey);
  const identityGroups = useMemo(
    () => environment ? groupInterfaceForwardingIdentities(environment, items) : [],
    [environment, items],
  );

  const reloadIdentities = useCallback(async () => {
    if (!workspaceId) { setItems([]); return; }
    try { setItems(await listInterfaceForwardingIdentities(workspaceId)); } catch (reason) { setError(reason instanceof Error ? reason.message : "请求身份加载失败"); }
  }, [workspaceId]);

  useEffect(() => { void reloadIdentities(); }, [reloadIdentities]);

  return (
    <ModalFrame title="转发配置" onClose={onClose} wide>
      <div className="interface-forwarding-config-layout">
        <aside className="interface-forwarding-environment-list">
          <header><strong>工作空间环境</strong><span>{environments.length}</span></header>
          {environments.map((item) => (
            <button key={item.environment_key} type="button" data-active={item.environment_key === environmentKey} onClick={() => setEnvironmentKey(item.environment_key)}>
              <span><strong>{item.display_name}</strong><code>{item.environment_key}</code></span>
              <small>{item.addresses.length ? `${item.addresses.length} 个地址` : "未配置"}</small>
            </button>
          ))}
        </aside>
        <div className="interface-forwarding-config-detail">
          {environment ? <>
            <header><div><h3>{environment.display_name}</h3><code>{environment.environment_key}</code></div><p>此处只展示 AI 维护的转发地址、接口服务映射和登录账号。</p></header>
            <section className="interface-forwarding-config-section">
              <div><h4>环境地址</h4><p>以下为当前环境的地址与接口服务映射；登录账号在下方按账号汇总。</p></div>
              <ul className="interface-forwarding-address-list">
                {environment.addresses.length ? environment.addresses.map((item) => (
                  <li key={item.id}>
                    <div>
                      <strong>{item.name} · {item.service_name || "未映射服务"}</strong>
                      <code title={item.base_url}>{item.base_url}</code>
                    </div>
                  </li>
                )) : <li className="interface-forwarding-config-empty">当前环境还没有转发地址</li>}
              </ul>
            </section>
            {identityGroups.length ? identityGroups.map((group) => (
              <section className="interface-forwarding-config-section interface-forwarding-account-card" key={group.key}>
                <div>
                  <h4 className="interface-forwarding-identity-heading"><strong>{group.loginAccount}</strong>{group.roleName ? <span className="interface-forwarding-role-badge">{group.roleName}</span> : null}</h4>
                  <p>已映射 {group.mappings.length} 个转发地址，以下内容均为只读展示。</p>
                </div>
                <ul className="interface-forwarding-identity-list">
                  {group.mappings.map(({ identity, address }) => (
                    <li key={identity.id}>
                      <div>
                        <strong>{address.name} · {address.service_name || "未映射服务"}</strong>
                        <code title={address.base_url}>{address.base_url}</code>
                        <code title={identity.request_header || "未配置请求头"}>{identity.request_header || "未配置请求头"}</code>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            )) : <section className="interface-forwarding-config-section"><div className="interface-forwarding-config-empty">当前环境还没有登录账号</div></section>}
          </> : <div className="interface-forwarding-empty">当前工作空间还没有环境。</div>}
        </div>
      </div>
      {error ? <p className="error-banner">{error}</p> : null}
    </ModalFrame>
  );
}

function InterfaceDetailModal({ item, onClose, onDelete }: { item: InterfaceForwardingInterface; onClose: () => void; onDelete: () => Promise<void> }) {
  const [section, setSection] = useState<"info" | "logs">("logs");
  return <ModalFrame title={item.name} onClose={onClose} wide><nav className="interface-forwarding-detail-tabs" aria-label="接口详情内容"><button type="button" data-active={section === "logs"} onClick={() => setSection("logs")}>请求日志</button><button type="button" data-active={section === "info"} onClick={() => setSection("info")}>接口信息</button></nav>{section === "logs" ? <LogsPanel item={item} /> : null}{section === "info" ? <InterfaceInfoPanel item={item} /> : null}<footer><button className="danger-text-button" type="button" onClick={() => void onDelete()}>删除接口</button><button className="secondary-button" type="button" onClick={onClose}>关闭</button></footer></ModalFrame>;
}

function InterfaceInfoPanel({ item }: { item: InterfaceForwardingInterface }) {
  return <div className="interface-forwarding-detail-info"><dl><div><dt>请求方式</dt><dd><span className={methodClass(item.method)}>{item.method}</span></dd></div><div><dt>接口路径</dt><dd><code title={item.path}>{item.path}</code></dd></div><div><dt>Controller 名称</dt><dd><code>{item.controller_name || "—"}</code></dd></div><div><dt>Controller 描述</dt><dd>{item.controller_description || "—"}</dd></div><div className="interface-forwarding-detail-wide"><dt>接口说明</dt><dd>{item.description || "当前接口文档没有提供说明"}</dd></div></dl><div className="interface-forwarding-detail-schemas"><details><summary>请求参数结构</summary><pre className="interface-forwarding-schema">{Object.keys(item.request_schema || {}).length ? JSON.stringify(item.request_schema, null, 2) : "当前接口文档没有声明请求参数结构"}</pre></details><details><summary>响应参数结构</summary><pre className="interface-forwarding-schema">{Object.keys(item.response_schema || {}).length ? JSON.stringify(item.response_schema, null, 2) : "当前接口文档没有声明响应参数结构"}</pre></details></div></div>;
}

function TestPanel({ item, environments }: { item: InterfaceForwardingInterface; environments: InterfaceForwardingEnvironment[] }) {
  const addresses = useMemo(() => environments.flatMap((environment) => environment.addresses.filter((address) => address.service_id === item.service_id).map((address) => ({ ...address, workspace_environment_name: environment.display_name }))), [environments, item.service_id]);
  const firstAddress = addresses[0]; const [environmentId, setEnvironmentId] = useState(firstAddress?.id || ""); const [identityId, setIdentityId] = useState(""); const [identities, setIdentities] = useState<InterfaceForwardingIdentity[]>([]); const [body, setBody] = useState("{}"); const [response, setResponse] = useState(""); const [resultMeta, setResultMeta] = useState(""); const [busy, setBusy] = useState(true); const [error, setError] = useState("");
  useEffect(() => { getInterfaceForwardingState(item.id).then((state) => { const previousAddress = addresses.some((address) => address.id === state.last_params?.environment_id) ? state.last_params?.environment_id : null; setEnvironmentId(previousAddress || firstAddress?.id || ""); setIdentityId(previousAddress ? state.last_params?.identity_id || "" : ""); setBody(state.last_params?.request_body || "{}"); setResponse(state.last_params?.response_body || ""); }).catch((reason: Error) => setError(reason.message)).finally(() => setBusy(false)); }, [addresses, firstAddress?.id, item.id]);
  useEffect(() => { if (!environmentId) { setIdentities([]); return; } listInterfaceForwardingIdentities(firstAddress?.workspace_id || "", environmentId).then(setIdentities).catch(() => setIdentities([])); }, [environmentId, firstAddress?.workspace_id]);
  async function execute() { setBusy(true); setError(""); try { JSON.parse(body || "{}"); const result = await executeInterfaceForwarding(item.id, { environment_id: environmentId, identity_id: identityId || undefined, request_body: body }); setResponse(result.response_body); setResultMeta(`${result.status_code ?? "请求失败"} · ${result.duration_ms} ms · ${result.success ? "成功" : "失败"}`); } catch (reason) { setError(reason instanceof Error ? reason.message : "请求失败"); } finally { setBusy(false); } }
  return <div><div className="interface-forwarding-test-toolbar"><label>转发地址<select value={environmentId} onChange={(event) => { setEnvironmentId(event.target.value); setIdentityId(""); }}><option value="">请选择转发地址</option>{addresses.map((address) => <option key={address.id} value={address.id}>{address.workspace_environment_name} · {address.name}</option>)}</select></label><label>登录账号<select value={identityId} onChange={(event) => setIdentityId(event.target.value)}><option value="">不使用账号</option>{identities.map((identity) => <option key={identity.id} value={identity.id}>{identity.login_account}</option>)}</select></label><code>{item.method} {item.path}</code></div><div className="interface-forwarding-editors"><label>请求参数<textarea value={body} onChange={(event) => setBody(event.target.value)} spellCheck={false} /></label><label>响应结果 {resultMeta ? <span>{resultMeta}</span> : null}<textarea readOnly value={response} spellCheck={false} /></label></div>{error ? <p className="error-banner">{error}</p> : null}<div className="interface-forwarding-detail-actions"><button className="primary-button" type="button" disabled={busy || !environmentId} onClick={() => void execute()}>{busy ? "请求中…" : "发送请求"}</button></div></div>;
}

function TestModal({ item, environments, onClose }: { item: InterfaceForwardingInterface; environments: InterfaceForwardingEnvironment[]; onClose: () => void }) {
  return <ModalFrame title={`${item.name} · 接口测试`} onClose={onClose} wide><TestPanel item={item} environments={environments} /><footer><button className="secondary-button" type="button" onClick={onClose}>关闭</button></footer></ModalFrame>;
}

function LogsPanel({ item }: { item: InterfaceForwardingInterface }) {
  const [logs, setLogs] = useState<InterfaceForwardingLog[]>([]); const [error, setError] = useState("");
  useEffect(() => { listInterfaceForwardingLogs(item.id).then(setLogs).catch((reason: Error) => setError(reason.message)); }, [item.id]);
  return <div>{error ? <p className="error-banner">{error}</p> : null}<div className="interface-forwarding-log-list">{logs.length === 0 ? <p>暂无请求日志</p> : logs.map((log) => <details key={log.id}><summary><span data-success={log.success}>{log.status_code ?? "ERR"}</span><strong>{log.environment_name}{log.identity_name ? ` · ${log.identity_name}` : ""}{log.identity_role ? ` · ${log.identity_role}` : ""}</strong><code>{log.duration_ms} ms</code><time>{new Date(log.created_at).toLocaleString("zh-CN")}</time></summary><dl><dt>URL</dt><dd><code>{log.request_url}</code></dd><dt>请求</dt><dd><pre>{log.request_body}</pre></dd><dt>响应</dt><dd><pre>{log.response_body}</pre></dd></dl></details>)}</div></div>;
}
