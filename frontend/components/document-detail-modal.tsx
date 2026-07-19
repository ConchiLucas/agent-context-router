"use client";

import { useEffect, useState } from "react";

import { DocumentDetailContent } from "@/components/document-detail-content";
import type { DocumentDetail } from "@/lib/types";

type DocumentDetailModalProps = Readonly<{
  documentId: string;
  onClose: () => void;
}>;

type LoadState =
  | {
      document: DocumentDetail;
      status: "loaded";
    }
  | {
      error: string;
      status: "error";
    }
  | {
      status: "loading";
    };

export function DocumentDetailModal({ documentId, onClose }: DocumentDetailModalProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoadState({ status: "loading" });

    async function loadDocument() {
      try {
        const response = await fetch(`/api/documents/${encodeURIComponent(documentId)}`, {
          headers: {
            Accept: "application/json",
          },
          cache: "no-store",
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`API request failed: ${response.status} ${response.statusText}`);
        }

        const document = (await response.json()) as DocumentDetail;
        setLoadState({ document, status: "loaded" });
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        setLoadState({
          error: error instanceof Error ? error.message : "Failed to load document.",
          status: "error",
        });
      }
    }

    void loadDocument();

    return () => {
      controller.abort();
    };
  }, [documentId, retryCount]);

  return (
    <aside
      aria-label="Document detail"
      aria-modal="true"
      className="project-modal nested-project-modal document-preview-modal"
      role="dialog"
    >
      <button
        aria-label="关闭"
        className="icon-close-button project-modal-close"
        onClick={onClose}
        title="关闭"
        type="button"
      >
        ×
      </button>
      <div className="project-modal-content">
        {loadState.status === "loaded" ? (
          <DocumentDetailContent document={loadState.document} />
        ) : null}
        {loadState.status === "loading" ? (
          <DocumentDetailLoading documentId={documentId} />
        ) : null}
        {loadState.status === "error" ? (
          <DocumentDetailError
            documentId={documentId}
            message={loadState.error}
            onRetry={() => setRetryCount((currentCount) => currentCount + 1)}
          />
        ) : null}
      </div>
    </aside>
  );
}

function DocumentDetailLoading({ documentId }: Readonly<{ documentId: string }>) {
  return (
    <>
      <header className="document-detail-header">
        <h1 className="page-title">Loading document</h1>
        <p className="document-detail-id">{documentId}</p>
      </header>
      <section className="section panel">
        <div className="route-loading">
          <span className="route-loading-bar" />
          <span>Loading detail...</span>
        </div>
      </section>
    </>
  );
}

function DocumentDetailError({
  documentId,
  message,
  onRetry,
}: Readonly<{
  documentId: string;
  message: string;
  onRetry: () => void;
}>) {
  return (
    <>
      <header className="document-detail-header">
        <h1 className="page-title">Document unavailable</h1>
        <p className="document-detail-id">{documentId}</p>
      </header>
      <section className="section panel document-detail-error">
        <p>{message}</p>
        <button className="button" onClick={onRetry} type="button">
          Retry
        </button>
      </section>
    </>
  );
}
