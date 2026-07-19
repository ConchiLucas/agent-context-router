import Link from "next/link";

import { eventDurationMs, payloadString, readDocumentIds } from "@/lib/task-trace";
import type { TraceDetail, TraceEvent } from "@/lib/types";

export function TaskDetail({ task }: Readonly<{ task: TraceDetail }>) {
  const prepareEvent = task.events.find((event) => event.event_type === "prepare");
  const readEvents = task.events.filter((event) => event.event_type === "read");
  const readIds = readDocumentIds(task.events);

  return (
    <>
      <header className="task-detail-header">
        <div>
          <Link className="task-back-link" href="/tasks">
            ← Tasks
          </Link>
          <h1 className="page-title">{task.task}</h1>
          <p className="page-subtitle">{task.id}</p>
        </div>
        <span className="badge">MCP</span>
      </header>

      <section className="section task-summary-grid">
        <Summary label="Project" value={task.project.slug} />
        <Summary label="AI tool" value={task.agent_name ?? "unknown"} />
        <Summary label="Working directory" value={task.cwd ?? "not supplied"} />
        <Summary label="Started" value={formatDate(task.created_at)} />
      </section>

      <section className="section panel task-chain-panel">
        <div className="task-chain-heading">
          <div>
            <h2 className="section-title">MCP call chain</h2>
            <p className="page-subtitle">Only calls and reads observed by Context Router are shown.</p>
          </div>
          <span>{task.events.length} events</span>
        </div>

        <div className="task-chain">
          <ChainStep
            detail={task.task}
            duration={prepareEvent ? eventDurationMs(prepareEvent) : null}
            index={1}
            name="prepare_task_context"
            timestamp={prepareEvent?.created_at ?? task.created_at}
          >
            <div className="candidate-grid">
              {task.retrieval_hits.length === 0 ? (
                <p className="task-muted">No candidate documents returned.</p>
              ) : (
                task.retrieval_hits.map((hit) => (
                  <article className="candidate-card" key={hit.id}>
                    <div>
                      <span>#{hit.rank}</span>
                      <strong>{hit.document_title}</strong>
                    </div>
                    <code>{hit.document_id}</code>
                    <p>{hit.reason}</p>
                    <span className={`candidate-state ${readIds.has(hit.document_id) ? "read" : "skipped"}`}>
                      {readIds.has(hit.document_id) ? "Read by AI" : "Returned only"}
                    </span>
                  </article>
                ))
              )}
            </div>
          </ChainStep>

          {readEvents.length === 0 ? (
            <div className="task-chain-empty">
              <span>2</span>
              <p>The AI did not call read_context_document for this task.</p>
            </div>
          ) : (
            readEvents.map((event, index) => (
              <ChainStep
                detail={readDetail(event)}
                duration={eventDurationMs(event)}
                index={index + 2}
                key={event.id}
                name="read_context_document"
                timestamp={event.created_at}
              >
                <div className="read-facts">
                  <Fact label="Document" value={payloadString(event, "document_id")} />
                  <Fact
                    label="Parent"
                    value={payloadString(event, "parent_document_id") || "task root"}
                  />
                </div>
              </ChainStep>
            ))
          )}
        </div>
      </section>
    </>
  );
}

function ChainStep({
  children,
  detail,
  duration,
  index,
  name,
  timestamp,
}: Readonly<{
  children: React.ReactNode;
  detail: string;
  duration: number | null;
  index: number;
  name: string;
  timestamp: string;
}>) {
  return (
    <article className="task-chain-step">
      <div className="task-chain-index">{index}</div>
      <div className="task-chain-content">
        <div className="task-chain-step-header">
          <div>
            <code>{name}</code>
            <p>{detail}</p>
          </div>
          <div className="task-chain-time">
            <span>{duration === null ? "—" : `${duration.toFixed(1)} ms`}</span>
            <time>{formatDate(timestamp)}</time>
          </div>
        </div>
        {children}
      </div>
    </article>
  );
}

function Summary({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="panel task-summary">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Fact({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div>
      <span>{label}</span>
      <code>{value}</code>
    </div>
  );
}

function readDetail(event: TraceEvent) {
  const documentId = payloadString(event, "document_id");
  return documentId ? `AI opened ${documentId}` : "AI opened a context document";
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}
