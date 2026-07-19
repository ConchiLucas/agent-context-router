import Link from "next/link";

import { TraceFlow } from "@/components/trace-flow";
import { getTrace } from "@/lib/api";

type TraceDetailPageProps = {
  params: Promise<{
    traceId: string;
  }>;
  searchParams: Promise<{
    document?: string;
    event?: string;
    step?: string;
  }>;
};

export default async function TraceDetailPage({ params, searchParams }: TraceDetailPageProps) {
  const { traceId } = await params;
  const { document, event, step } = await searchParams;
  const result = await Promise.allSettled([getTrace(traceId)]);
  const trace = result[0].status === "fulfilled" ? result[0].value : null;

  if (trace === null) {
    return (
      <section className="panel">
        <h1 className="page-title">Trace unavailable</h1>
        <p className="page-subtitle">{traceId}</p>
        <Link aria-label="关闭" className="icon-close-button page-close-button" href="/traces" title="关闭">
          ×
        </Link>
      </section>
    );
  }

  return (
    <section className="trace-workspace">
      <header className="trace-workspace-header">
        <div className="trace-workspace-heading">
          <div className="trace-workspace-meta">
            <span className="trace-workspace-kicker">Trace Workflow</span>
            <span className="trace-workspace-id">{trace.id}</span>
          </div>
          <h1>{trace.task}</h1>
        </div>
        <div className="trace-workspace-badges">
          <span className="badge">{trace.project.slug}</span>
          {trace.area ? <span className="badge">{trace.area}</span> : null}
        </div>
        <Link aria-label="关闭" className="icon-close-button trace-close-button" href="/traces" title="关闭">
          ×
        </Link>
      </header>

      <TraceFlow
        selectedDocumentId={document}
        selectedEventId={event}
        selectedStep={step}
        trace={trace}
      />
    </section>
  );
}
