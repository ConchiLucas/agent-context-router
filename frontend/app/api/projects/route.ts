import { NextRequest, NextResponse } from "next/server";

const API_BASE_URL =
  process.env.CONTEXT_ROUTER_INTERNAL_API_URL ?? "http://127.0.0.1:8000";

export async function POST(request: NextRequest) {
  const response = await fetch(`${API_BASE_URL}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    cache: "no-store",
  });
  const payload = await response.text();

  return new NextResponse(payload, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") ?? "application/json" },
  });
}
