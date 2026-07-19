import type { TraceEvent } from "./types";

export function readDocumentIds(events: TraceEvent[]) {
  return new Set(
    events
      .filter((event) => event.event_type === "read")
      .map((event) => event.payload.document_id)
      .filter((documentId): documentId is string => typeof documentId === "string")
  );
}

export function eventDurationMs(event: TraceEvent) {
  const duration = event.payload.duration_ms;
  return typeof duration === "number" && Number.isFinite(duration) ? duration : null;
}

export function payloadString(event: TraceEvent, key: string) {
  const value = event.payload[key];
  return typeof value === "string" ? value : "";
}

export function payloadDisplay(event: TraceEvent, key: string) {
  const value = event.payload[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

export function entryReturnLabel(count: number) {
  return `${count} ${count === 1 ? "entry" : "entries"} returned`;
}
