import { DocumentDetailView } from "@/components/document-detail-view";

type DocumentDetailPageProps = {
  params: Promise<{
    documentId: string;
  }>;
};

export default async function DocumentDetailPage({ params }: DocumentDetailPageProps) {
  const { documentId } = await params;

  return <DocumentDetailView backHref="/documents" documentId={documentId} />;
}
