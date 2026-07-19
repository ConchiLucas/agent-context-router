"use client";

import Link from "next/link";
import type { MouseEvent, ReactNode } from "react";
import { useEffect, useState } from "react";

import { FeedbackControls } from "@/components/feedback-controls";
import { MarkdownContent } from "@/components/markdown-content";
import type { RetrievalHit, TraceDetail, TraceEvent } from "@/lib/types";

type TraceFlowProps = Readonly<{
  trace: TraceDetail;
  selectedDocumentId?: string;
  selectedEventId?: string;
  selectedStep?: string;
}>;

type ReadEvent = TraceEvent & {
  event_type: "read";
};

const feedbackClassMap: Record<string, string> = {
  missing: "badge-missing",
  stale: "badge-stale",
  unnecessary: "badge-unnecessary",
  useful: "badge-useful",
};

export function TraceFlow({
  trace,
  selectedDocumentId,
  selectedEventId,
  selectedStep,
}: TraceFlowProps) {
  const [selection, setSelection] = useState({
    documentId: selectedDocumentId ?? null,
    eventId: selectedEventId ?? null,
    step: selectedStep ?? null,
  });

  useEffect(() => {
    function syncFromHistory() {
      setSelection(selectionFromUrl(window.location.href));
    }

    window.addEventListener("popstate", syncFromHistory);

    return () => {
      window.removeEventListener("popstate", syncFromHistory);
    };
  }, []);

  const prepareEvent = trace.events.find((event) => event.event_type === "prepare");
  const readEvents = trace.events.filter(isReadEvent);
  const feedbackEvents = trace.events.filter((event) => event.event_type === "feedback");
  const usedPrepareFallback = Boolean(prepareEvent) || trace.retrieval_hits.length > 0;
  const readDocumentIds = new Set(readEvents.map((event) => payloadString(event, "document_id")));
  const selectedHit = selection.documentId
    ? trace.retrieval_hits.find((hit) => hit.document_id === selection.documentId)
    : null;
  const selectedEvent = selection.eventId
    ? trace.events.find((event) => event.id === selection.eventId)
    : null;
  const detail = (
    <TraceFlowDetail
      event={selectedEvent ?? null}
      hit={selectedHit ?? null}
      prepareEvent={prepareEvent ?? null}
      readEvents={readEvents}
      selectedStep={selection.step ?? undefined}
      trace={trace}
    />
  );

  function handleTraceClick(event: MouseEvent<HTMLElement>) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey) {
      return;
    }
    if (event.shiftKey || event.altKey) {
      return;
    }

    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }

    const link = target.closest("a");
    if (!(link instanceof HTMLAnchorElement) || link.target) {
      return;
    }

    const nextUrl = new URL(link.href, window.location.href);
    if (!isCurrentTraceUrl(nextUrl, trace.id)) {
      return;
    }

    event.preventDefault();
    setSelection(selectionFromUrl(nextUrl.href));
    window.history.pushState(null, "", `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`);
  }

  return (
    <section className="trace-flow-layout" onClickCapture={handleTraceClick}>
      {detail}

      <div className="trace-flow-scroll panel">
        <div className="trace-flow">
            <TraceStep title="1. Entry" subtitle="一次上下文读取会话的起点">
            <TraceNode
              active={selection.step === "task"}
              href={traceHref(trace.id, { step: "task" })}
              label="Entry"
              title={entryTitle(trace, readEvents)}
            >
              <TraceNodeMeta value={trace.project.slug} />
              {trace.area ? <TraceNodeMeta value={trace.area} /> : null}
              {trace.source ? <TraceNodeMeta value={trace.source} /> : null}
              {readEvents[0] ? (
                <TraceNodeMeta value={`first: ${payloadString(readEvents[0], "document_id")}`} />
              ) : null}
            </TraceNode>
          </TraceStep>

          <TraceArrow />

          <TraceStep title="2. Document Path" subtitle="AI 按 ctx read 实际读取的文档树路径">
            {readEvents.length === 0 ? (
              <EmptyTraceNode message="No documents read yet." />
            ) : (
              <div className="trace-node-list">
                {readEvents.map((event, index) => (
                  <TraceNode
                    active={selection.eventId === event.id}
                    href={traceHref(trace.id, { event: event.id })}
                    key={event.id}
                    label={readEventLabel(event, index)}
                    title={readEventTitle(event)}
                  >
                    <TraceNodeMeta value={payloadString(event, "document_id")} />
                    {payloadString(event, "parent_document_id") ? (
                      <TraceNodeMeta value={`from: ${payloadString(event, "parent_document_id")}`} />
                    ) : (
                      <TraceNodeMeta value="entry document" />
                    )}
                    <TraceNodeMeta value={readModeLabel(payloadString(event, "read_mode"))} />
                    <TraceNodeMeta value={formatDate(event.created_at)} />
                  </TraceNode>
                ))}
              </div>
            )}
          </TraceStep>

          <TraceArrow />

          <TraceStep title="3. Fallback Prepare" subtitle="不知道 doc-id 时才使用的兜底检索">
            {!usedPrepareFallback ? (
              <EmptyTraceNode message="No prepare fallback used." />
            ) : (
              <div className="trace-node-list">
                {prepareEvent ? (
                  <TraceNode
                    active={selection.step === "prepare"}
                    href={traceHref(trace.id, { step: "prepare" })}
                    label="ctx prepare"
                    title={prepareCommand(trace)}
                  >
                    <TraceNodeMeta value={trace.id} />
                    <TraceNodeMeta value={`${trace.retrieval_hits.length} returned`} />
                  </TraceNode>
                ) : null}
                {trace.retrieval_hits.map((hit) => (
                  <TraceNode
                    active={selection.documentId === hit.document_id}
                    href={traceHref(trace.id, { document: hit.document_id })}
                    key={hit.id}
                    label={`Rank ${hit.rank}`}
                    title={hit.document_title}
                  >
                    <TraceNodeMeta value={hit.document_id} />
                    <TraceNodeMeta value={`Score ${hit.score.toFixed(2)}`} />
                    <TraceNodeMeta
                      tone={readDocumentIds.has(hit.document_id) ? "success" : "muted"}
                      value={readDocumentIds.has(hit.document_id) ? "Read" : "Returned only"}
                    />
                    {hit.feedback ? (
                      <span className={`badge ${feedbackClassMap[hit.feedback] ?? ""}`}>
                        {hit.feedback}
                      </span>
                    ) : null}
                  </TraceNode>
                ))}
              </div>
            )}
          </TraceStep>

          <TraceArrow />

          <TraceStep title="4. Feedback" subtitle="对推荐文档或缺失上下文的标注">
            {feedbackEvents.length === 0 ? (
              <EmptyTraceNode message="No feedback yet." />
            ) : (
              <div className="trace-node-list">
                {feedbackEvents.map((event) => (
                  <TraceNode
                    active={selection.eventId === event.id}
                    href={traceHref(trace.id, { event: event.id })}
                    key={event.id}
                    label={payloadString(event, "feedback") || "Feedback"}
                    title={payloadString(event, "document_id") || "Unknown document"}
                  >
                    <TraceNodeMeta value={formatDate(event.created_at)} />
                    {payloadString(event, "note") ? (
                      <p>{payloadString(event, "note")}</p>
                    ) : null}
                  </TraceNode>
                ))}
              </div>
            )}
          </TraceStep>
        </div>
      </div>
    </section>
  );
}

function TraceStep({
  children,
  subtitle,
  title,
}: Readonly<{
  children: ReactNode;
  subtitle: string;
  title: string;
}>) {
  return (
    <div className="trace-flow-step">
      <div className="trace-flow-step-header">
        <strong>{title}</strong>
        <span>{subtitle}</span>
      </div>
      {children}
    </div>
  );
}

function TraceArrow() {
  return <div aria-hidden="true" className="trace-flow-arrow" />;
}

function TraceNode({
  active,
  children,
  href,
  label,
  title,
}: Readonly<{
  active?: boolean;
  children: ReactNode;
  href: string;
  label: string;
  title: string;
}>) {
  return (
    <Link className={`trace-node ${active ? "active" : ""}`} href={href}>
      <span className="trace-node-label">{label}</span>
      <strong>{title}</strong>
      <div className="trace-node-body">{children}</div>
    </Link>
  );
}

function TraceNodeMeta({
  tone,
  value,
}: Readonly<{
  tone?: "muted" | "success";
  value: string;
}>) {
  return <span className={`trace-node-meta ${tone ?? ""}`}>{value}</span>;
}

function EmptyTraceNode({ message }: Readonly<{ message: string }>) {
  return (
    <div className="trace-node empty">
      <span className="trace-node-label">Empty</span>
      <strong>{message}</strong>
    </div>
  );
}

function TraceFlowDetail({
  event,
  hit,
  prepareEvent,
  readEvents,
  selectedStep,
  trace,
}: Readonly<{
  event: TraceEvent | null;
  hit: RetrievalHit | null;
  prepareEvent: TraceEvent | null;
  readEvents: ReadEvent[];
  selectedStep?: string;
  trace: TraceDetail;
}>) {
  const baseHref = `/traces/${encodeURIComponent(trace.id)}`;
  const documentReadEvents = hit
    ? readEvents.filter((readEvent) => payloadString(readEvent, "document_id") === hit.document_id)
    : [];

  if (hit) {
    return (
      <aside className="trace-flow-detail panel">
        <DetailHeader backHref={baseHref} title="Document Call Detail" />
        <div className="trace-detail-grid">
          <DetailItem label="Document" value={hit.document_id} />
          <DetailItem label="Title" value={hit.document_title} />
          <DetailItem label="Rank" value={String(hit.rank)} />
          <DetailItem label="Score" value={hit.score.toFixed(2)} />
          <DetailItem label="Returned" value={hit.was_returned ? "yes" : "no"} />
          <DetailItem label="Feedback" value={hit.feedback ?? "none"} />
        </div>
        <section className="trace-detail-section">
          <h3>Prepare Reason</h3>
          <p>{hit.reason}</p>
        </section>
        <section className="trace-detail-section">
          <h3>Read Events</h3>
          {documentReadEvents.length === 0 ? (
            <p>这份文档只被返回，还没有后续 read 记录。</p>
          ) : (
            documentReadEvents.map((readEvent) => (
              <div className="trace-detail-event" key={readEvent.id}>
                <strong>{formatDate(readEvent.created_at)}</strong>
                <span>{readModeLabel(payloadString(readEvent, "read_mode"))}</span>
                <small>{payloadString(readEvent, "source") || "source unknown"}</small>
              </div>
            ))
          )}
        </section>
        <section className="trace-detail-section">
          <h3>Actions</h3>
          <div className="trace-detail-actions">
            <Link className="button" href={`/documents/${encodeURIComponent(hit.document_id)}`}>
              Open Document
            </Link>
            <FeedbackControls
              currentFeedback={hit.feedback}
              documentId={hit.document_id}
              traceId={trace.id}
            />
          </div>
        </section>
      </aside>
    );
  }

  if (event) {
    const documentId = payloadString(event, "document_id");
    const isRead = event.event_type === "read";
    return (
      <aside className="trace-flow-detail panel">
        <DetailHeader backHref={baseHref} title={isRead ? "Document Read Detail" : "Event Detail"} />
        <div className="trace-detail-grid">
          <DetailItem label="Event" value={event.event_type} />
          <DetailItem label="Event ID" value={event.id} />
          <DetailItem label="Time" value={formatDate(event.created_at)} />
          {isRead ? (
            <>
              <DetailItem label="Document" value={documentId || "unknown"} />
              <DetailItem
                label="Parent"
                value={payloadString(event, "parent_document_id") || "entry document"}
              />
              <DetailItem label="Depth" value={payloadString(event, "depth") || "unknown"} />
              <DetailItem
                label="Mode"
                value={readModeLabel(payloadString(event, "read_mode"))}
              />
            </>
          ) : null}
        </div>
        <section className="trace-detail-section">
          <h3>Payload</h3>
          <PayloadTable payload={event.payload} />
        </section>
        {isRead && documentId ? (
          <section className="trace-detail-section">
            <h3>Actions</h3>
            <div className="trace-detail-actions">
              <Link className="button" href={`/documents/${encodeURIComponent(documentId)}`}>
                Open Document
              </Link>
            </div>
          </section>
        ) : null}
      </aside>
    );
  }

  if (selectedStep === "task") {
    return (
      <aside className="trace-flow-detail trace-prompt-detail panel">
        <DetailHeader backHref={baseHref} title="提示词详情" />
        <div className="trace-detail-grid">
          <DetailItem label="Project" value={trace.project.slug} />
          <DetailItem label="Area" value={trace.area ?? "general"} />
          <DetailItem label="Source" value={trace.source ?? "unknown"} />
          <DetailItem label="Agent" value={trace.agent_name ?? "unknown"} />
          <DetailItem label="Created" value={formatDate(trace.created_at)} />
        </div>
        <section className="trace-detail-section">
          <h3>Prompt</h3>
          <MarkdownContent content={taskPromptMarkdown(trace)} />
        </section>
      </aside>
    );
  }

  if (selectedStep === "prepare") {
    return (
      <aside className="trace-flow-detail panel">
        <DetailHeader backHref={baseHref} title="Prepare Detail" />
        <div className="trace-detail-grid">
          <DetailItem label="Command" value={prepareCommand(trace)} />
          <DetailItem label="Trace ID" value={trace.id} />
          <DetailItem label="Returned Docs" value={String(trace.retrieval_hits.length)} />
          <DetailItem label="Entrypoint Path" value={trace.entrypoint_path ?? "none"} />
          <DetailItem label="Entrypoint Rule" value={trace.entrypoint_rule ?? "none"} />
          <DetailItem label="Route Hint" value={trace.route_hint ?? "none"} />
        </div>
        {prepareEvent ? (
          <section className="trace-detail-section">
            <h3>Prepare Payload</h3>
            <PayloadTable payload={prepareEvent.payload} />
          </section>
        ) : null}
      </aside>
    );
  }

  return null;
}

function DetailHeader({ backHref, title }: Readonly<{ backHref: string; title: string }>) {
  return (
    <div className="trace-detail-header">
      <h2 className="section-title">{title}</h2>
      <Link aria-label="关闭详情" className="icon-close-button panel-close-button" href={backHref} title="关闭详情">
        ×
      </Link>
    </div>
  );
}

function DetailItem({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="trace-detail-item">
      <strong>{label}</strong>
      <span title={value}>{value}</span>
    </div>
  );
}

function PayloadTable({ payload }: Readonly<{ payload: Record<string, unknown> }>) {
  const entries = Object.entries(payload);
  if (entries.length === 0) {
    return <p>No payload recorded.</p>;
  }

  return (
    <div className="trace-payload-table">
      {entries.map(([key, value]) => (
        <div key={key}>
          <strong>{key}</strong>
          <span>{formatPayloadValue(value)}</span>
        </div>
      ))}
    </div>
  );
}

function traceHref(
  traceId: string,
  params: { document?: string; event?: string; step?: string }
) {
  const searchParams = new URLSearchParams();
  if (params.document) {
    searchParams.set("document", params.document);
  }
  if (params.event) {
    searchParams.set("event", params.event);
  }
  if (params.step) {
    searchParams.set("step", params.step);
  }
  return `/traces/${encodeURIComponent(traceId)}?${searchParams.toString()}`;
}

function isCurrentTraceUrl(url: URL, traceId: string) {
  if (url.origin !== window.location.origin) {
    return false;
  }
  const pathParts = url.pathname.split("/").filter(Boolean);
  return pathParts.length === 2 && pathParts[0] === "traces" && pathParts[1] === traceId;
}

function selectionFromUrl(url: string) {
  const searchParams = new URL(url, window.location.href).searchParams;
  return {
    documentId: searchParams.get("document"),
    eventId: searchParams.get("event"),
    step: searchParams.get("step"),
  };
}

function prepareCommand(trace: TraceDetail) {
  const areaPart = trace.area ? ` --area ${trace.area}` : "";
  return `ctx prepare --project ${trace.project.slug}${areaPart}`;
}

function entryTitle(trace: TraceDetail, readEvents: ReadEvent[]) {
  const firstReadTitle = readEvents[0] ? readEventTitle(readEvents[0]) : "";
  return firstReadTitle ? `从 ${firstReadTitle} 开始` : trace.task;
}

function readEventLabel(event: ReadEvent, index: number) {
  const depth = payloadString(event, "depth");
  return depth ? `Depth ${depth}` : `Read ${index + 1}`;
}

function readEventTitle(event: ReadEvent) {
  return (
    payloadString(event, "document_title") ||
    payloadString(event, "document_id") ||
    "Unknown document"
  );
}

function taskPromptMarkdown(trace: TraceDetail) {
  return [
    "## 入口内容",
    "",
    trace.task,
    "",
    "## 路由上下文",
    "",
    `- Project: \`${trace.project.slug}\``,
    `- Area: \`${trace.area ?? "general"}\``,
    `- Source: \`${trace.source ?? "unknown"}\``,
    `- Agent: \`${trace.agent_name ?? "unknown"}\``,
    `- Trace ID: \`${trace.id}\``,
  ].join("\n");
}

function readModeLabel(value: string) {
  if (value === "tree_read") {
    return "按文档树继续读取";
  }
  if (value === "prepare_fallback") {
    return "兜底检索后读取";
  }
  if (value === "current_trace") {
    return "基于当前上下文读取";
  }
  if (value === "direct_read") {
    return "直接读取，系统自动创建调用记录";
  }
  return "读取事件已记录";
}

function isReadEvent(event: TraceEvent): event is ReadEvent {
  return event.event_type === "read";
}

function payloadString(event: TraceEvent, key: string) {
  const value = event.payload[key];
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

function formatPayloadValue(value: unknown) {
  if (value === null || value === undefined) {
    return "null";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value));
}
