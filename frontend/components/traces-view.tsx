import { TraceTimeline } from "@/components/trace-timeline";
import { getTraces } from "@/lib/api";

export type TraceFilters = {
  project?: string;
  area?: string;
  source?: string;
};

type TracesViewProps = Readonly<{
  filters: TraceFilters;
  subtitle?: string;
}>;

export async function TracesView({
  filters,
  subtitle = filters.project
    ? `Document read paths, fallback prepare calls, and feedback for ${filters.project}.`
    : "Document read paths, fallback prepare calls, and feedback.",
}: TracesViewProps) {
  const result = await Promise.allSettled([getTraces(filters)]);
  const traces = result[0].status === "fulfilled" ? result[0].value.traces : [];

  return (
    <>
      <header>
        <h1 className="page-title">Traces</h1>
        <p className="page-subtitle">{subtitle}</p>
      </header>
      <section className="section grid">
        {traces.length === 0 ? (
          <div className="panel">
            <p className="page-subtitle">No traces recorded yet.</p>
          </div>
        ) : (
          traces.map((trace) => <TraceTimeline key={trace.id} trace={trace} />)
        )}
      </section>
    </>
  );
}
