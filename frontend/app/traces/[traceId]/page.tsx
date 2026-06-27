import { FeedbackControls } from "@/components/feedback-controls";
import { RetrievalHitList } from "@/components/retrieval-hit-list";
import { getTrace } from "@/lib/api";
import type { TraceDetail } from "@/lib/types";

type TraceDetailPageProps = {
  params: Promise<{
    traceId: string;
  }>;
};

export default async function TraceDetailPage({ params }: TraceDetailPageProps) {
  const { traceId } = await params;
  const result = await Promise.allSettled([getTrace(traceId)]);
  const trace = result[0].status === "fulfilled" ? result[0].value : null;

  if (trace === null) {
    return (
      <section className="panel">
        <h1 className="page-title">Trace unavailable</h1>
        <p className="page-subtitle">{traceId}</p>
      </section>
    );
  }

  return (
    <>
      <header>
        <span className="badge">{trace.project.slug}</span>
        <h1 className="page-title">{trace.task}</h1>
        <p className="page-subtitle">{trace.id}</p>
      </header>

      <section className="section panel">
        <h2 className="section-title">Routing Metadata</h2>
        <TraceMetadata trace={trace} />
      </section>

      <section className="section panel">
        <h2 className="section-title">Returned Documents</h2>
        <RetrievalHitList hits={trace.retrieval_hits}>
          {(hit) => (
            <FeedbackControls
              currentFeedback={hit.feedback}
              documentId={hit.document_id}
              traceId={trace.id}
            />
          )}
        </RetrievalHitList>
      </section>

      <section className="section grid two-column">
        <div className="panel">
          <h2 className="section-title">Read Events</h2>
          <ReadEvents trace={trace} />
        </div>
        <div className="panel">
          <h2 className="section-title">Routing Notes</h2>
          <RoutingNotes trace={trace} />
        </div>
      </section>
    </>
  );
}

function TraceMetadata({ trace }: Readonly<{ trace: TraceDetail }>) {
  const items = [
    ["Area", trace.area],
    ["Source", trace.source],
    ["Agent", trace.agent_name],
    ["Working Directory", trace.cwd],
    ["Entrypoint Path", trace.entrypoint_path],
    ["Entrypoint Rule", trace.entrypoint_rule],
    ["Route Hint", trace.route_hint],
  ].filter((item): item is [string, string] => Boolean(item[1]));

  if (items.length === 0) {
    return <p className="page-subtitle">No routing metadata recorded.</p>;
  }

  return (
    <div className="stack">
      {items.map(([label, value]) => (
        <div className="event-row" key={label}>
          <strong>{label}</strong>
          <span>{value}</span>
        </div>
      ))}
    </div>
  );
}

function ReadEvents({ trace }: Readonly<{ trace: TraceDetail }>) {
  const readEvents = trace.events.filter((event) => event.event_type === "read");
  if (readEvents.length === 0) {
    return <p className="page-subtitle">No document reads recorded.</p>;
  }

  return (
    <div className="stack">
      {readEvents.map((event) => (
        <div className="event-row" key={event.id}>
          <strong>{String(event.payload.document_id)}</strong>
          <span>{String(event.payload.reason ?? "")}</span>
        </div>
      ))}
    </div>
  );
}

function RoutingNotes({ trace }: Readonly<{ trace: TraceDetail }>) {
  const unnecessary = trace.retrieval_hits.filter((hit) => hit.feedback === "unnecessary");
  const stale = trace.retrieval_hits.filter((hit) => hit.feedback === "stale");
  const readDocumentIds = new Set(
    trace.events
      .filter((event) => event.event_type === "read")
      .map((event) => String(event.payload.document_id ?? ""))
      .filter(Boolean)
  );
  const returnedUnread = trace.retrieval_hits.filter((hit) => !readDocumentIds.has(hit.document_id));
  const returnedIds = new Set(trace.retrieval_hits.map((hit) => hit.document_id));
  const readWithoutReturned = [...readDocumentIds].filter((documentId) => !returnedIds.has(documentId));

  if (
    unnecessary.length === 0 &&
    stale.length === 0 &&
    returnedUnread.length === 0 &&
    readWithoutReturned.length === 0
  ) {
    return <p className="page-subtitle">No routing issues marked yet.</p>;
  }

  return (
    <div className="stack">
      {returnedUnread.map((hit) => (
        <p className="page-subtitle" key={`unread-${hit.id}`}>
          Returned but unread: {hit.document_id}.
        </p>
      ))}
      {readWithoutReturned.map((documentId) => (
        <p className="page-subtitle" key={`read-without-returned-${documentId}`}>
          Read without being returned: {documentId}.
        </p>
      ))}
      {unnecessary.map((hit) => (
        <p className="page-subtitle" key={`unnecessary-${hit.id}`}>
          Reduce matching weight for {hit.document_id} on similar tasks.
        </p>
      ))}
      {stale.map((hit) => (
        <p className="page-subtitle" key={`stale-${hit.id}`}>
          Refresh or archive {hit.document_id}.
        </p>
      ))}
    </div>
  );
}
