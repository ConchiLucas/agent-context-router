"use client";

import { useCallback, useEffect, useState } from "react";

import { useVisualizationWorkspaces } from "@/components/visualization-record-explorer";
import { listInterfacePromptMatches } from "@/lib/api";
import type {
  InterfacePromptClientJudgment,
  InterfacePromptIdentity,
  InterfacePromptMatch,
  PromptClientName,
  PromptClientStatus,
} from "@/lib/types";

const WORKSPACE_STORAGE_KEY = "interface-prompt-lab.workspace-id";
const CLIENT_STORAGE_KEY = "interface-prompt-lab.client";
const REFRESH_MS = 20000;
const PAGE_SIZE = 20;
const CLIENT_LABEL: Record<PromptClientName, string> = {
  codex: "Codex",
  "codex-root": "Codex Root",
  "codex-astra": "Codex Astra",
  cursor: "Cursor",
  antigravity: "Antigravity",
};

const CLIENT_STATUS_LABEL: Record<PromptClientStatus, string> = {
  missing: "尚未返回",
  searching: "检索中",
  selected: "已选择",
  clarify: "应澄清",
  violated: "协议违规",
  failed: "调用失败",
};

function pickWorkspaceId(items: { id: string; name: string }[], stored: string | null): string {
  if (stored && items.some((item) => item.id === stored)) return stored;
  return items.find((item) => item.name.includes("攀枝花"))?.id || items[0]?.id || "";
}

function clientOf(item: InterfacePromptMatch, name: PromptClientName) {
  return item.clients.find((client) => client.client === name) ?? null;
}

function identityKey(method?: string | null, path?: string | null): string {
  if (!method || !path) return "";
  return `${method.toUpperCase()} ${path}`;
}

function matchState(
  client: InterfacePromptClientJudgment | null,
  expected: InterfacePromptIdentity | null,
): "same" | "diff" | "empty" {
  const returned = identityKey(client?.selected_method, client?.selected_path);
  const correct = identityKey(expected?.method, expected?.path);
  if (!returned) return "empty";
  if (!correct) return "empty";
  return returned === correct ? "same" : "diff";
}

function isClientName(value: string | null): value is PromptClientName {
  return (
    value === "codex" ||
    value === "codex-root" ||
    value === "codex-astra" ||
    value === "cursor" ||
    value === "antigravity"
  );
}

export function InterfacePromptLab() {
  const { workspaces, workspaceError, workspaceLoading } = useVisualizationWorkspaces();
  const [workspaceId, setWorkspaceId] = useState("");
  const [client, setClient] = useState<PromptClientName>("antigravity");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<InterfacePromptMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!workspaces.length) return;
    const stored = window.localStorage.getItem(WORKSPACE_STORAGE_KEY);
    setWorkspaceId((current) => current || pickWorkspaceId(workspaces, stored));
  }, [workspaces]);

  useEffect(() => {
    if (!workspaceId) return;
    window.localStorage.setItem(WORKSPACE_STORAGE_KEY, workspaceId);
  }, [workspaceId]);

  useEffect(() => {
    const stored = window.localStorage.getItem(CLIENT_STORAGE_KEY);
    if (isClientName(stored)) setClient(stored);
  }, []);

  useEffect(() => {
    window.localStorage.setItem(CLIENT_STORAGE_KEY, client);
  }, [client]);

  const loadRows = useCallback(async (nextWorkspaceId: string, nextPage: number, silent = false) => {
    if (!nextWorkspaceId) {
      setItems([]);
      setTotal(0);
      return;
    }
    if (!silent) {
      setLoading(true);
      setError("");
    }
    try {
      const result = await listInterfacePromptMatches(nextWorkspaceId, nextPage, PAGE_SIZE, client);
      setItems(result.items);
      setTotal(result.total);
      const lastPage = Math.max(1, Math.ceil(result.total / result.page_size) || 1);
      if (nextPage > lastPage) setPage(lastPage);
    } catch (reason) {
      setItems([]);
      setTotal(0);
      setError(reason instanceof Error ? reason.message : "读取对照记录失败");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    void loadRows(workspaceId, page);
  }, [loadRows, workspaceId, page]);

  useEffect(() => {
    if (!workspaceId) return;
    const timer = window.setInterval(() => {
      void loadRows(workspaceId, page, true);
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [loadRows, workspaceId, page]);

  return (
    <section className="interface-prompt-lab" aria-label="接口测试">
      <div className="interface-prompt-lab-toolbar">
        <label>
          工作空间
          <select
            value={workspaceId}
            disabled={workspaceLoading || !workspaces.length}
            onChange={(event) => {
              setWorkspaceId(event.target.value);
              setPage(1);
            }}
          >
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          客户端
          <select
            value={client}
            onChange={(event) => {
              setClient(event.target.value as PromptClientName);
              setPage(1);
            }}
          >
            <option value="antigravity">Antigravity</option>
            <option value="cursor">Cursor</option>
            <option value="codex-root">Codex Root</option>
            <option value="codex-astra">Codex Astra</option>
            <option value="codex">Codex</option>
          </select>
        </label>
      </div>
      {workspaceError || error ? (
        <p className="error-banner" role="alert">
          {error || workspaceError}
        </p>
      ) : null}
      <div className="interface-prompt-lab-table-wrap">
        {loading ? <p className="empty-message">正在读取对照记录…</p> : null}
        {!loading && !items.length ? (
          <p className="empty-message">还没有对照记录。受支持的执行者用 MCP 裁定后会出现在这里。</p>
        ) : null}
        {!loading && items.length ? (
          <table className="interface-prompt-lab-table">
            <thead>
              <tr>
                <th>提示词</th>
                <th>客户端</th>
                <th>返回接口</th>
                <th>正确接口</th>
                <th>对错</th>
                <th>易混点</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const expected = item.expected;
                const judgment = clientOf(item, client);
                const match = matchState(judgment, expected);
                return (
                  <tr key={item.id}>
                    <td>
                      <p className="interface-prompt-lab-prompt">{item.prompt}</p>
                    </td>
                    <td>
                      <span className="interface-prompt-lab-client-name">{CLIENT_LABEL[client]}</span>
                    </td>
                    <td>
                      <ClientResult judgment={judgment} match={match} />
                    </td>
                    <td>
                      <InterfaceCell identity={expected} empty="未标注" />
                    </td>
                    <td>
                      <Verdict match={match} />
                    </td>
                    <td>
                      <p className="interface-prompt-lab-note">{item.note || "—"}</p>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : null}
      </div>
      {total ? (
        <PromptMatchPager
          page={page}
          total={total}
          pageSize={PAGE_SIZE}
          busy={loading}
          onPage={setPage}
        />
      ) : null}
    </section>
  );
}

function PromptMatchPager({
  page,
  total,
  pageSize,
  busy,
  onPage,
}: {
  page: number;
  total: number;
  pageSize: number;
  busy: boolean;
  onPage: (page: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const [draftPage, setDraftPage] = useState(String(page));
  useEffect(() => {
    setDraftPage(String(page));
  }, [page]);
  const commitPage = () => {
    const next = Number(draftPage);
    if (Number.isInteger(next) && next >= 1 && next <= totalPages) {
      onPage(next);
      return;
    }
    setDraftPage(String(page));
  };
  return (
    <div className="interface-prompt-lab-pager">
      <p>共 {total} 条</p>
      <nav className="relation-record-pager" aria-label="对照表分页">
        <button type="button" aria-label="首页" disabled={busy || page <= 1} onClick={() => onPage(1)}>
          ┃◀
        </button>
        <button type="button" aria-label="上一页" disabled={busy || page <= 1} onClick={() => onPage(page - 1)}>
          ◀
        </button>
        <label>
          <span className="sr-only">当前页</span>
          <input
            type="number"
            min={1}
            max={totalPages}
            value={draftPage}
            disabled={busy}
            onChange={(event) => setDraftPage(event.target.value)}
            onBlur={commitPage}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitPage();
              }
            }}
          />
        </label>
        <span aria-label={`共 ${totalPages} 页`}>/ {totalPages}</span>
        <button type="button" aria-label="下一页" disabled={busy || page >= totalPages} onClick={() => onPage(page + 1)}>
          ▶
        </button>
        <button type="button" aria-label="末页" disabled={busy || page >= totalPages} onClick={() => onPage(totalPages)}>
          ▶┃
        </button>
      </nav>
    </div>
  );
}

function ClientResult({
  judgment,
  match,
}: {
  judgment: InterfacePromptClientJudgment | null;
  match: "same" | "diff" | "empty";
}) {
  const status = judgment?.status ?? "missing";
  const hasInterface = Boolean(judgment?.selected_path);
  return (
    <div className="interface-prompt-lab-client" data-match={hasInterface ? match : "empty"}>
      {hasInterface ? (
        <InterfaceCell
          identity={{
            interface_id: judgment?.selected_interface_id ?? null,
            method: judgment?.selected_method ?? "",
            path: judgment?.selected_path ?? "",
            title: judgment?.selected_title ?? "",
            service: "",
          }}
        />
      ) : (
        <p>{CLIENT_STATUS_LABEL[status]}</p>
      )}
    </div>
  );
}

function InterfaceCell({
  identity,
  empty = "尚未返回",
}: {
  identity: InterfacePromptIdentity | null | undefined;
  empty?: string;
}) {
  if (!identity?.path) {
    return <p className="interface-prompt-lab-empty">{empty}</p>;
  }
  return (
    <p className="interface-prompt-lab-identity">
      {identity.service ? <small>{identity.service}</small> : null}
      <span className="http-method">{identity.method}</span>
      <code>{identity.path}</code>
      {identity.title ? <small>{identity.title}</small> : null}
    </p>
  );
}

const VERDICT_LABEL = {
  same: "一致",
  diff: "不一致",
  empty: "未返回",
} as const;

function Verdict({ match }: { match: "same" | "diff" | "empty" }) {
  return (
    <p className="interface-prompt-lab-verdict" data-match={match}>
      {VERDICT_LABEL[match]}
    </p>
  );
}
