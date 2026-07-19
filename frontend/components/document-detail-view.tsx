import Link from "next/link";

import { DocumentDetailContent } from "@/components/document-detail-content";
import { getDocument } from "@/lib/api";

type DocumentDetailViewProps = Readonly<{
  documentId: string;
  backHref: string;
  backLabel?: string;
  showInlineBack?: boolean;
}>;

export async function DocumentDetailView({
  documentId,
  backHref,
  backLabel = "关闭",
  showInlineBack = true,
}: DocumentDetailViewProps) {
  const result = await Promise.allSettled([getDocument(documentId)]);
  const document = result[0].status === "fulfilled" ? result[0].value : null;

  if (document === null) {
    return (
      <section className="panel">
        <h1 className="page-title">Document unavailable</h1>
        <p className="page-subtitle">{documentId}</p>
        {showInlineBack ? (
          <Link
            aria-label="关闭"
            className="icon-close-button page-close-button"
            href={backHref}
            title="关闭"
          >
            ×
          </Link>
        ) : null}
      </section>
    );
  }

  return (
    <DocumentDetailContent
      closeControl={
        showInlineBack ? (
          <Link
            aria-label={backLabel}
            className="icon-close-button page-close-button"
            href={backHref}
            title={backLabel}
          >
            ×
          </Link>
        ) : null
      }
      document={document}
    />
  );
}
