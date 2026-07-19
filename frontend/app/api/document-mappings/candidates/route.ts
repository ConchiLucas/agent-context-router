import { NextResponse } from "next/server";

const API_BASE_URL =
  process.env.CONTEXT_ROUTER_INTERNAL_API_URL ??
  process.env.NEXT_PUBLIC_CONTEXT_ROUTER_API_URL ??
  "http://127.0.0.1:8000";

export async function GET() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/document-mappings/candidates`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("content-type") ?? "application/json" },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown mapping error";
    return NextResponse.json({ detail: message }, { status: 502 });
  }
}
