import Link from "next/link";

import { getTasks } from "@/lib/api";
import { entryReturnLabel } from "@/lib/task-trace";

type TaskListProps = Readonly<{
  filters?: Record<string, string | undefined>;
  showHeader?: boolean;
}>;

export async function TaskList({ filters = {}, showHeader = true }: TaskListProps) {
  const result = await Promise.allSettled([getTasks(filters)]);
  const tasks = result[0].status === "fulfilled" ? result[0].value.traces : [];

  return (
    <>
      {showHeader ? (
        <header>
          <h1 className="page-title">Tasks</h1>
          <p className="page-subtitle">
            AI tasks that called Context Router through MCP. Open a task to inspect its document chain.
          </p>
        </header>
      ) : null}
      <section className="section task-list">
        {tasks.length === 0 ? (
          <div className="panel task-empty">
            <strong>No MCP tasks recorded yet</strong>
            <p className="page-subtitle">
              Tasks appear here after an AI calls prepare_task_context.
            </p>
          </div>
        ) : (
          tasks.map((task) => (
            <Link className="task-row" href={`/tasks/${task.id}`} key={task.id}>
              <div className="task-row-main">
                <strong>{task.task}</strong>
                <span>{formatDate(task.created_at)}</span>
              </div>
              <div className="task-row-meta">
                <span className="badge">{task.project_slug}</span>
                <span>{task.agent_name ?? "unknown AI"}</span>
                <span>{entryReturnLabel(task.returned_document_count)}</span>
                <span>{task.read_event_count} reads</span>
                <span>{formatDuration(task.mcp_duration_ms)}</span>
              </div>
            </Link>
          ))
        )}
      </section>
    </>
  );
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

function formatDuration(value: number) {
  return `${value.toFixed(1)} ms MCP`;
}
