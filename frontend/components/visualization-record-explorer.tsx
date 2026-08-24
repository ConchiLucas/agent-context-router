"use client";

import {
  type ReactNode,
  useCallback,
  useEffect,
  useState,
} from "react";

import { listWorkspaces } from "@/lib/api";
import type { WorkspaceSummary } from "@/lib/types";

interface VisualizationPage<TItem> {
  items: TItem[];
  has_more: boolean;
  next_cursor?: string | null;
}

export function useVisualizationWorkspaces() {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspaceError, setWorkspaceError] = useState("");
  const [workspaceLoading, setWorkspaceLoading] = useState(true);

  const reloadWorkspaces = useCallback(async () => {
    setWorkspaceLoading(true);
    setWorkspaceError("");
    try {
      setWorkspaces(await listWorkspaces());
    } catch (reason) {
      setWorkspaces([]);
      setWorkspaceError(reason instanceof Error ? reason.message : "工作空间加载失败");
    } finally {
      setWorkspaceLoading(false);
    }
  }, []);

  useEffect(() => {
    void reloadWorkspaces();
  }, [reloadWorkspaces]);

  return {
    workspaces,
    workspaceError,
    workspaceLoading,
    reloadWorkspaces,
  };
}

export function useVisualizationRecords<
  TItem extends { id: string },
  TDetail extends { id: string },
>({
  filterKey,
  loadPage,
  loadDetail,
  listErrorMessage,
  detailErrorMessage,
}: {
  filterKey: string;
  loadPage: (cursor?: string) => Promise<VisualizationPage<TItem>>;
  loadDetail: (id: string) => Promise<TDetail>;
  listErrorMessage: string;
  detailErrorMessage: string;
}) {
  const [items, setItems] = useState<TItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<TDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");

  const loadRecords = useCallback(async (append = false) => {
    append ? setLoadingMore(true) : setLoading(true);
    setError("");
    try {
      const result = await loadPage(append ? nextCursor ?? undefined : undefined);
      setItems((current) => {
        const nextItems = append ? [...current, ...result.items] : result.items;
        setSelectedId((selected) =>
          nextItems.some((item) => item.id === selected)
            ? selected
            : (nextItems[0]?.id ?? ""),
        );
        return nextItems;
      });
      setNextCursor(result.has_more ? result.next_cursor ?? null : null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : listErrorMessage);
      if (!append) {
        setItems([]);
        setSelectedId("");
        setNextCursor(null);
      }
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [listErrorMessage, loadPage, nextCursor]);

  useEffect(() => {
    setItems([]);
    setSelectedId("");
    setNextCursor(null);
    void loadRecords(false);
    // loadRecords includes the current cursor; filters alone initiate a fresh page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey, loadPage]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailError("");
      return;
    }
    let active = true;
    setDetailLoading(true);
    setDetailError("");
    loadDetail(selectedId)
      .then((result) => {
        if (active) setDetail(result);
      })
      .catch((reason) => {
        if (active) {
          setDetail(null);
          setDetailError(reason instanceof Error ? reason.message : detailErrorMessage);
        }
      })
      .finally(() => {
        if (active) setDetailLoading(false);
      });
    return () => {
      active = false;
    };
  }, [detailErrorMessage, loadDetail, selectedId]);

  return {
    items,
    selectedId,
    setSelectedId,
    detail,
    loading,
    loadingMore,
    detailLoading,
    error,
    detailError,
    hasMore: Boolean(nextCursor),
    refresh: () => loadRecords(false),
    loadMore: () => loadRecords(true),
  };
}

export function VisualizationRecordLayout({
  listLabel,
  list,
  detail,
}: {
  listLabel: string;
  list: ReactNode;
  detail: ReactNode;
}) {
  return (
    <div className="interface-visualization-layout">
      <aside className="interface-request-list" aria-label={listLabel}>{list}</aside>
      <article className="interface-request-detail" aria-live="polite">{detail}</article>
    </div>
  );
}

export function CopyVisualizationButton({
  value,
  label = "复制脱敏内容",
}: {
  value: string;
  label?: string;
}) {
  const [status, setStatus] = useState<"idle" | "copied" | "failed">("idle");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setStatus("copied");
      window.setTimeout(() => setStatus("idle"), 1800);
    } catch {
      setStatus("failed");
    }
  };

  return (
    <button
      type="button"
      className="secondary-button visualization-copy-button"
      onClick={() => void copy()}
      aria-live="polite"
    >
      {status === "copied" ? "已复制" : status === "failed" ? "复制失败" : label}
    </button>
  );
}
