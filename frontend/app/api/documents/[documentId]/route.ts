import { NextResponse } from "next/server";

const API_BASE_URL =
  process.env.CONTEXT_ROUTER_INTERNAL_API_URL ??
  process.env.NEXT_PUBLIC_CONTEXT_ROUTER_API_URL ??
  "http://127.0.0.1:8000";

type RouteContext = {
  params: Promise<{
    documentId: string;
  }>;
};

export async function GET(_request: Request, context: RouteContext) {
  const { documentId } = await context.params;

  try {
    const response = await fetch(
      `${API_BASE_URL}/api/documents/${encodeURIComponent(documentId)}?untracked=true`,
      {
        headers: {
          Accept: "application/json",
        },
        cache: "no-store",
      },
    );
    const responseBody = await response.text();
    const contentType = response.headers.get("content-type") ?? "application/json";

    return new Response(responseBody, {
      status: response.status,
      headers: {
        "Content-Type": contentType,
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown document error";
    return NextResponse.json({ detail: message }, { status: 502 });
  }
}
