import type {
  ContextReadHistoryCall,
  ContextReadHistoryItem,
} from "@/lib/types";

export interface TaskReadStep {
  sequence: number;
  callNumber: number;
  readCallId: number;
  createdAt: string;
  document: ContextReadHistoryItem;
}

export interface TaskReadRow {
  callNumber: number;
  readCallId: number;
  createdAt: string;
  steps: TaskReadStep[];
}

export function buildTaskReadRows(
  calls: ContextReadHistoryCall[],
): TaskReadRow[] {
  let sequence = 0;

  return calls.map((call, callIndex) => {
    const callNumber = callIndex + 1;
    const steps = call.documents.map((document) => {
      sequence += 1;
      return {
        sequence,
        callNumber,
        readCallId: call.read_call_id,
        createdAt: call.created_at,
        document,
      };
    });

    return {
      callNumber,
      readCallId: call.read_call_id,
      createdAt: call.created_at,
      steps,
    };
  });
}

export function buildTaskReadSteps(
  calls: ContextReadHistoryCall[],
): TaskReadStep[] {
  return buildTaskReadRows(calls).flatMap((row) => row.steps);
}

export function buildDocumentCallNumbers(
  calls: ContextReadHistoryCall[],
): ReadonlyMap<string, number[]> {
  const callNumbersByDocumentId = new Map<string, number[]>();

  calls.forEach((call, callIndex) => {
    const callNumber = callIndex + 1;
    const documentIds = new Set(
      call.documents.map((document) => document.document_id),
    );

    documentIds.forEach((documentId) => {
      const callNumbers = callNumbersByDocumentId.get(documentId) ?? [];
      callNumbersByDocumentId.set(documentId, [...callNumbers, callNumber]);
    });
  });

  return callNumbersByDocumentId;
}
