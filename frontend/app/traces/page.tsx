import { TracesView } from "@/components/traces-view";

type TracesPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function TracesPage({ searchParams }: TracesPageProps) {
  const params = await searchParams;
  const filters = {
    project: singleValue(params.project),
    area: singleValue(params.area),
    source: singleValue(params.source),
  };

  return <TracesView filters={filters} />;
}

function singleValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}
