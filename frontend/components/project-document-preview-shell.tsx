"use client";

import type { MouseEvent, ReactNode } from "react";
import { useEffect, useState } from "react";

import { DocumentDetailModal } from "@/components/document-detail-modal";

type ProjectDocumentPreviewShellProps = Readonly<{
  children: ReactNode;
  closeHref: string;
  initialDocumentId?: string | null;
}>;

export function ProjectDocumentPreviewShell({
  children,
  closeHref,
  initialDocumentId = null,
}: ProjectDocumentPreviewShellProps) {
  const [documentId, setDocumentId] = useState<string | null>(initialDocumentId);

  useEffect(() => {
    function syncFromHistory() {
      const currentUrl = new URL(window.location.href);
      setDocumentId(currentUrl.searchParams.get("document"));
    }

    window.addEventListener("popstate", syncFromHistory);

    return () => {
      window.removeEventListener("popstate", syncFromHistory);
    };
  }, []);

  function handleClick(event: MouseEvent<HTMLDivElement>) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey) {
      return;
    }
    if (event.shiftKey || event.altKey) {
      return;
    }

    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }

    const link = target.closest("a");
    if (!(link instanceof HTMLAnchorElement) || link.target) {
      return;
    }

    const nextUrl = new URL(link.href, window.location.href);
    if (nextUrl.origin !== window.location.origin || nextUrl.pathname !== "/projects") {
      return;
    }

    const nextDocumentId = nextUrl.searchParams.get("document");
    if (!nextDocumentId) {
      return;
    }

    event.preventDefault();
    setDocumentId(nextDocumentId);
    window.history.pushState(null, "", `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`);
  }

  function closeDocument() {
    setDocumentId(null);
    window.history.pushState(null, "", closeHref);
  }

  return (
    <>
      <div onClickCapture={handleClick}>{children}</div>
      {documentId ? (
        <DocumentDetailModal documentId={documentId} onClose={closeDocument} />
      ) : null}
    </>
  );
}
