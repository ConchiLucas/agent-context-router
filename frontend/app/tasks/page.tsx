import { TaskList } from "@/components/task-list";

type TasksPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function TasksPage({ searchParams }: TasksPageProps) {
  const params = await searchParams;

  return (
    <TaskList
      filters={{
        project: singleValue(params.project),
        area: singleValue(params.area),
      }}
    />
  );
}

function singleValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}
