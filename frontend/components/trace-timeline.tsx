import type { TraceSummary } from "@/lib/types";
import Link from "next/link";

export function TraceTimeline({ trace }: Readonly<{ trace: TraceSummary }>) {
  return (
    <Link className="panel row-card" href={`/traces/${trace.id}`}>
      <span className="badge">{trace.project_slug}</span>
      <h2>{trace.task}</h2>
      <p className="page-subtitle">{trace.id}</p>
      <div className="split-row">
        <span>{trace.returned_document_count} returned</span>
        <span>{trace.read_event_count} reads</span>
        <span>{trace.feedback_count} feedback</span>
      </div>
    </Link>
  );
}
