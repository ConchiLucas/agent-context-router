import { TraceTimeline } from "@/components/trace-timeline";
import { getTraces } from "@/lib/api";

export default async function TracesPage() {
  const result = await Promise.allSettled([getTraces()]);
  const traces = result[0].status === "fulfilled" ? result[0].value.traces : [];
  return (
    <>
      <header>
        <h1 className="page-title">Traces</h1>
        <p className="page-subtitle">Prepare calls, read history, and feedback.</p>
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
