"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { getSharedConfigurationCatalog, saveSharedAiDefault } from "@/lib/api";
import type {
  SharedAiProvider,
  SharedConfigurationCatalog,
  SharedDatabaseConnection,
  SharedLocalCliItem,
} from "@/lib/types";

type ConfigSection = "databases" | "ai" | "cli" | "minio" | "image" | "runtime";
type SecretKey = string;

const NAV_ITEMS: Array<{ key: ConfigSection; label: string }> = [
  { key: "databases", label: "数据库配置" },
  { key: "ai", label: "AI 配置" },
  { key: "cli", label: "本地 CLI 配置" },
  { key: "minio", label: "MinIO 配置" },
  { key: "image", label: "图片模型配置" },
  { key: "runtime", label: "Runtime Contract" },
];

const HEADINGS: Record<ConfigSection, { eyebrow: string; title: string; description: string }> = {
  databases: { eyebrow: "CONFIGURATION / DATABASES", title: "Database Connections", description: "展示 Shared Config Center 提供的跨语言数据库连接参数。" },
  ai: { eyebrow: "CONFIGURATION / AI", title: "AI Provider", description: "展示由 Shared Config Center 提供的 AI 服务配置。" },
  cli: { eyebrow: "CONFIGURATION / LOCAL CLI", title: "本地 CLI 配置", description: "展示命令、参数与本地执行上下文配置。" },
  minio: { eyebrow: "CONFIGURATION / MINIO", title: "MinIO 配置", description: "展示 S3-compatible 对象存储连接信息。" },
  image: { eyebrow: "CONFIGURATION / IMAGE MODEL", title: "图片模型配置", description: "展示配置中心筛选出的可执行图片 Provider。" },
  runtime: { eyebrow: "RUNTIME / VERSION 1", title: "Runtime Contract", description: "展示配置中心当前生成的完整运行契约。" },
};

function displayOptions(options: Record<string, unknown>) {
  const entries = Object.entries(options);
  return entries.length ? entries.map(([key, value]) => `${key}=${String(value)}`).join(", ") : "—";
}

function ReadonlyField({ label, value, wide = false, code = false }: { label: string; value: string; wide?: boolean; code?: boolean }) {
  return <label className={`shared-ai-field${wide ? " shared-ai-field--wide" : ""}`}><span>{label}</span><input readOnly value={value || "—"} className={code ? "shared-ai-code" : ""} /></label>;
}

function SecretField({ label, value, secretKey, visible, onToggle }: { label: string; value: string; secretKey: SecretKey; visible: boolean; onToggle: (key: SecretKey) => void }) {
  return <label className="shared-ai-field"><span>{label}</span><div className="shared-ai-secret"><input readOnly type={visible ? "text" : "password"} value={value || "—"} /><button type="button" className="shared-ai-eye" aria-label={`${visible ? "隐藏" : "显示"} ${label}`} onClick={() => onToggle(secretKey)}>{visible ? "◉" : "◌"}</button></div></label>;
}

function NavIcon({ section }: { section: ConfigSection }) {
  if (section === "databases") return <><ellipse cx="12" cy="5" rx="7" ry="3" /><path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" /></>;
  if (section === "ai") return <><rect x="5" y="7" width="14" height="11" rx="2" /><path d="M9 11h.01M15 11h.01M9 15h6M12 7V4M10 4h4M3 11v3M21 11v3" /></>;
  if (section === "cli") return <path d="m5 7 4 5-4 5M11 17h8" />;
  if (section === "minio") return <path d="M6 18h12a4 4 0 0 0 .4-8A6 6 0 0 0 7 8.5 4.5 4.5 0 0 0 6 18Z" />;
  if (section === "image") return <><rect x="4" y="4" width="16" height="16" rx="2" /><circle cx="9" cy="9" r="1.5" /><path d="m5 18 5-5 3 3 2-2 4 4" /></>;
  return <><path d="M8 3c-2 0-2 2-2 4v2c0 2-1 3-2 3 1 0 2 1 2 3v2c0 2 0 4 2 4M16 3c2 0 2 2 2 4v2c0 2 1 3 2 3-1 0-2 1-2 3v2c0 2 0 4-2 4" /></>;
}

function ConfigNav({ section, onChange }: { section: ConfigSection; onChange: (value: ConfigSection) => void }) {
  return <aside className="shared-ai-nav" aria-label="配置导航"><span>Configuration</span><div className="shared-ai-nav-list" role="menu">{NAV_ITEMS.map((item) => <button key={item.key} type="button" role="menuitem" className="shared-ai-nav-item" data-active={section === item.key} aria-current={section === item.key ? "page" : undefined} onClick={() => onChange(item.key)}><svg className="shared-ai-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><NavIcon section={item.key} /></svg><span>{item.label}</span></button>)}</div></aside>;
}

function ProviderCard({ provider, index, selected, selectable, visibleSecrets, onSelect, onToggleSecret }: { provider: SharedAiProvider; index: number; selected: boolean; selectable: boolean; visibleSecrets: Set<SecretKey>; onSelect?: () => void; onToggleSecret: (key: SecretKey) => void }) {
  const secretKey = `provider:${provider.id}`;
  return <fieldset className={`shared-ai-card${provider.active ? " shared-ai-card--active" : ""}`}><legend>{selectable ? "PROVIDER" : `IMAGE PROVIDER ${String(index + 1).padStart(2, "0")}`}</legend><div className="shared-ai-card-head">{selectable ? <label className="shared-ai-default-choice"><input type="radio" name="shared-ai-default" checked={selected} onChange={onSelect} />设为默认</label> : <strong>{provider.label || provider.id}</strong>}<span className={provider.active ? "shared-ai-state shared-ai-state--active" : "shared-ai-state"}>{provider.active ? "当前默认" : provider.enabled ? "已启用" : "未启用"}</span></div><div className="shared-ai-grid"><ReadonlyField label="Provider ID" value={provider.id} code /><ReadonlyField label="显示名称" value={provider.label} /><ReadonlyField label="Provider Type" value={provider.type} /><ReadonlyField label="Model" value={provider.model} /><ReadonlyField label="Base URL" value={provider.base_url} wide code /><ReadonlyField label="Max Tokens" value={String(provider.max_tokens)} /><SecretField label="API Key" value={provider.api_key} secretKey={secretKey} visible={visibleSecrets.has(secretKey)} onToggle={onToggleSecret} /><ReadonlyField label="Voice · 可选" value={provider.voice} /><ReadonlyField label="Capabilities" value={provider.capabilities.join(", ")} wide code /><ReadonlyField label="Options" value={displayOptions(provider.options)} wide code /></div></fieldset>;
}

function DatabaseCard({ item, index, visibleSecrets, onToggleSecret }: { item: SharedDatabaseConnection; index: number; visibleSecrets: Set<SecretKey>; onToggleSecret: (key: SecretKey) => void }) {
  const secretKey = `database:${item.id}`;
  return <fieldset className="shared-ai-card"><legend>DATABASE {String(index + 1).padStart(2, "0")}</legend><div className="shared-ai-grid"><ReadonlyField label="Connection ID" value={item.id} code /><ReadonlyField label="Display Name" value={item.name} /><ReadonlyField label="Database Type" value={item.type} /><ReadonlyField label="Environment" value={item.environment} /><ReadonlyField label="Host" value={item.host} code /><ReadonlyField label="Port" value={String(item.port)} /><ReadonlyField label="Database" value={item.database} code /><ReadonlyField label="Username" value={item.username} /><SecretField label="Password" value={item.password} secretKey={secretKey} visible={visibleSecrets.has(secretKey)} onToggle={onToggleSecret} /><ReadonlyField label="Parameters" value={displayOptions(item.parameters)} wide code /></div></fieldset>;
}

function CliCard({ item, index }: { item: SharedLocalCliItem; index: number }) {
  return <fieldset className={`shared-ai-card${item.active ? " shared-ai-card--active" : ""}`}><legend>CLI {String(index + 1).padStart(2, "0")}</legend><div className="shared-ai-card-head"><strong>{item.label || item.id}</strong><span className={item.active ? "shared-ai-state shared-ai-state--active" : "shared-ai-state"}>{item.active ? "配置中心默认" : item.enabled ? "已启用" : "未启用"}</span></div><div className="shared-ai-grid"><ReadonlyField label="配置 ID" value={item.id} code /><ReadonlyField label="显示名称" value={item.label} /><ReadonlyField label="命令路径" value={item.command} wide code /><ReadonlyField label="默认参数" value={item.default_args.join(" ")} wide code /><ReadonlyField label="模型" value={item.model} /><ReadonlyField label="推理强度" value={item.reasoning_effort} /><ReadonlyField label="默认工作目录" value={item.working_directory} wide code /><ReadonlyField label="超时（秒）" value={String(item.timeout_seconds)} /><ReadonlyField label="Capabilities" value={item.capabilities.join(", ")} wide code /></div></fieldset>;
}

function redactRuntime(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redactRuntime);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => {
    const normalized = key.toLowerCase();
    const secret = normalized.includes("password") || normalized.includes("apikey") || normalized.includes("secretaccesskey") || normalized.includes("accesskeyid");
    return [key, secret && typeof item === "string" && item ? "••••••••" : redactRuntime(item)];
  }));
}

function ConfigList({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return <><div className="shared-ai-toolbar"><strong>{title}</strong><span>{count} 个配置</span></div>{count ? <div className="shared-ai-list">{children}</div> : <p className="empty-message">暂无配置。</p>}</>;
}

export function SharedAiConfigManager() {
  const [section, setSection] = useState<ConfigSection>("databases");
  const [catalog, setCatalog] = useState<SharedConfigurationCatalog | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [visibleSecrets, setVisibleSecrets] = useState<Set<SecretKey>>(new Set());
  const [runtimeVisible, setRuntimeVisible] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const applyCatalog = useCallback((next: SharedConfigurationCatalog) => { setCatalog(next); setSelectedId(next.ai.active_provider_id); setVisibleSecrets(new Set()); setRuntimeVisible(false); }, []);
  const load = useCallback(async () => { setLoading(true); setError(""); try { applyCatalog(await getSharedConfigurationCatalog()); } catch (cause) { setError(cause instanceof Error ? cause.message : "无法读取共享配置中心"); } finally { setLoading(false); } }, [applyCatalog]);
  useEffect(() => { void load(); }, [load]);

  const selected = useMemo(() => catalog?.ai.providers.find((provider) => provider.id === selectedId) ?? null, [catalog, selectedId]);
  const toggleSecret = (key: SecretKey) => setVisibleSecrets((current) => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  const save = async () => { if (!catalog || !selected) return; setSaving(true); setError(""); try { const ai = await saveSharedAiDefault(selected.id, catalog.ai.revision); applyCatalog({ ...catalog, ai }); } catch (cause) { setError(cause instanceof Error ? cause.message : "默认 AI 保存失败"); } finally { setSaving(false); } };

  const heading = HEADINGS[section];
  return <section className="shared-ai-page" aria-label="配置管理"><ConfigNav section={section} onChange={(next) => { setSection(next); setVisibleSecrets(new Set()); setRuntimeVisible(false); }} /><div className="shared-ai-content"><header className="shared-ai-heading"><div><p className="section-eyebrow">{heading.eyebrow}</p><h1>{heading.title}</h1><p>{heading.description}</p></div><button type="button" className="secondary-button" onClick={() => void load()} disabled={loading || saving}>重新加载配置</button></header>{error ? <p className="error-banner" role="alert">{error}</p> : null}{catalog?.ai.notice && section === "ai" ? <p className="shared-ai-notice" role="status">{catalog.ai.notice}</p> : null}{loading ? <p className="empty-message">正在读取共享配置中心…</p> : null}{!loading && catalog ? <>{section === "databases" ? <ConfigList title="Connections" count={catalog.databases.length}>{catalog.databases.map((item, index) => <DatabaseCard key={item.id} item={item} index={index} visibleSecrets={visibleSecrets} onToggleSecret={toggleSecret} />)}</ConfigList> : null}{section === "ai" ? <ConfigList title="Providers" count={catalog.ai.providers.length}>{catalog.ai.providers.map((provider, index) => <ProviderCard key={provider.id} provider={provider} index={index} selectable selected={selectedId === provider.id} visibleSecrets={visibleSecrets} onSelect={() => setSelectedId(provider.id)} onToggleSecret={toggleSecret} />)}</ConfigList> : null}{section === "cli" ? <ConfigList title="CLI Registry" count={catalog.local_cli.configs.length}>{catalog.local_cli.configs.map((item, index) => <CliCard key={item.id} item={item} index={index} />)}</ConfigList> : null}{section === "minio" ? catalog.object_storage.configured ? <ConfigList title="S3 Compatible Contract" count={1}><fieldset className="shared-ai-card"><legend>MINIO</legend><div className="shared-ai-grid"><ReadonlyField label="Endpoint" value={catalog.object_storage.endpoint} wide code /><ReadonlyField label="Bucket Name" value={catalog.object_storage.bucket_name} /><ReadonlyField label="Base Path · 可选" value={catalog.object_storage.base_path} /><ReadonlyField label="使用 SSL" value={catalog.object_storage.use_ssl ? "是" : "否"} /><SecretField label="Access Key ID" value={catalog.object_storage.access_key_id} secretKey="minio:access" visible={visibleSecrets.has("minio:access")} onToggle={toggleSecret} /><SecretField label="Secret Access Key" value={catalog.object_storage.secret_access_key} secretKey="minio:secret" visible={visibleSecrets.has("minio:secret")} onToggle={toggleSecret} /></div></fieldset></ConfigList> : <p className="empty-message">配置中心尚未配置 MinIO。</p> : null}{section === "image" ? <ConfigList title="Providers" count={catalog.image_models.providers.length}>{catalog.image_models.providers.map((provider, index) => <ProviderCard key={provider.id} provider={provider} index={index} selectable={false} selected={false} visibleSecrets={visibleSecrets} onToggleSecret={toggleSecret} />)}</ConfigList> : null}{section === "runtime" ? <div className="shared-ai-runtime"><div className="shared-ai-runtime-head"><span>schemaVersion {String(catalog.runtime.schemaVersion ?? "—")}</span><button type="button" className="secondary-button" onClick={() => setRuntimeVisible((value) => !value)}>{runtimeVisible ? "隐藏契约密钥" : "显示契约密钥"}</button></div><pre>{JSON.stringify(runtimeVisible ? catalog.runtime : redactRuntime(catalog.runtime), null, 2)}</pre></div> : null}{section === "ai" && catalog.ai.providers.length > 0 ? <footer className="shared-ai-actions"><button type="button" className="primary-button" onClick={() => void save()} disabled={!selected || saving}>{saving ? "正在保存…" : "保存默认"}</button></footer> : null}</> : null}</div></section>;
}
