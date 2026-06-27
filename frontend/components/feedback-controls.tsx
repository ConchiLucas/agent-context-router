"use client";

import { useState } from "react";

import { contextRouterApiUrl } from "@/lib/api";
import type { TraceFeedback } from "@/lib/types";

const feedbackValues: { value: TraceFeedback; label: string; icon: React.ReactNode }[] = [
  {
    value: "useful",
    label: "Useful",
    icon: (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="20 6 9 17 4 12" />
      </svg>
    )
  },
  {
    value: "unnecessary",
    label: "Unnecessary",
    icon: (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" y1="6" x2="6" y2="18" />
        <line x1="6" y1="6" x2="18" y2="18" />
      </svg>
    )
  },
  {
    value: "stale",
    label: "Stale",
    icon: (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    )
  },
  {
    value: "missing",
    label: "Missing",
    icon: (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    )
  }
];

type FeedbackControlsProps = Readonly<{
  traceId: string;
  documentId: string;
  currentFeedback: TraceFeedback | null;
}>;

export function FeedbackControls({
  traceId,
  documentId,
  currentFeedback,
}: FeedbackControlsProps) {
  const [selected, setSelected] = useState<TraceFeedback | null>(currentFeedback);
  const [isSaving, setIsSaving] = useState(false);

  async function submitFeedback(feedback: TraceFeedback) {
    setIsSaving(true);
    try {
      const response = await fetch(`${contextRouterApiUrl()}/api/traces/${traceId}/feedback`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          document_id: documentId,
          feedback,
          note: "",
        }),
      });

      if (!response.ok) {
        throw new Error(`Feedback failed: ${response.status}`);
      }

      setSelected(feedback);
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="feedback-row" aria-label={`Feedback for ${documentId}`} style={{ display: "flex", gap: "0.5rem" }}>
      {feedbackValues.map((item) => {
        const isActive = selected === item.value;
        return (
          <button
            className={`feedback-btn ${isActive ? `active ${item.value}` : ""}`}
            disabled={isSaving}
            key={item.value}
            onClick={() => void submitFeedback(item.value)}
            type="button"
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}
