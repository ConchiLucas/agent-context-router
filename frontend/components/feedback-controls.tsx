"use client";

import { useState } from "react";

import { contextRouterApiUrl } from "@/lib/api";
import type { TraceFeedback } from "@/lib/types";

const feedbackValues: TraceFeedback[] = ["useful", "unnecessary", "missing", "stale"];

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
    <div className="feedback-row" aria-label={`Feedback for ${documentId}`}>
      {feedbackValues.map((feedback) => (
        <button
          className={selected === feedback ? "button active" : "button"}
          disabled={isSaving}
          key={feedback}
          onClick={() => void submitFeedback(feedback)}
          type="button"
        >
          {feedback}
        </button>
      ))}
    </div>
  );
}
