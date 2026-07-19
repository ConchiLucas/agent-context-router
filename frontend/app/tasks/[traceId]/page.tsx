import Link from "next/link";

import { TaskDetail } from "@/components/task-detail";
import { getTask } from "@/lib/api";

type TaskDetailPageProps = {
  params: Promise<{ traceId: string }>;
};

export default async function TaskDetailPage({ params }: TaskDetailPageProps) {
  const { traceId } = await params;
  const result = await Promise.allSettled([getTask(traceId)]);
  const task = result[0].status === "fulfilled" ? result[0].value : null;

  if (task === null || task.source !== "mcp") {
    return (
      <section className="panel task-empty">
        <h1 className="page-title">Task unavailable</h1>
        <p className="page-subtitle">{traceId}</p>
        <Link className="button" href="/tasks">
          Back to Tasks
        </Link>
      </section>
    );
  }

  return <TaskDetail task={task} />;
}
