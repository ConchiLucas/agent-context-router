import { DocumentsView } from "@/components/documents-view";

type DocumentsPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function DocumentsPage({ searchParams }: DocumentsPageProps) {
  const params = await searchParams;
  const filters = {
    project: singleValue(params.project),
    area: singleValue(params.area),
    doc_type: singleValue(params.doc_type),
    tag: singleValue(params.tag),
    status: singleValue(params.status),
  };

  return <DocumentsView filters={filters} />;
}

function singleValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}
