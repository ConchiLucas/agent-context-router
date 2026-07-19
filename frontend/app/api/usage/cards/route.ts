import { NextResponse } from "next/server";

const API_BASE_URL =
  process.env.CONTEXT_ROUTER_INTERNAL_API_URL ??
  process.env.NEXT_PUBLIC_CONTEXT_ROUTER_API_URL ??
  "http://127.0.0.1:8000";

export async function GET() {
  return proxyUsageCards("GET");
}

export async function POST(request: Request) {
  const requestBody = await request.text();
  return proxyUsageCards("POST", requestBody || "{}");
}

async function proxyUsageCards(method: "GET" | "POST", body?: string) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/usage/cards`, {
      method,
      headers: body
        ? {
            "Content-Type": "application/json",
          }
        : undefined,
      body,
      cache: "no-store",
    });
    const responseBody = await response.text();
    const contentType = response.headers.get("content-type") ?? "application/json";

    return new Response(responseBody, {
      status: response.status,
      headers: {
        "Content-Type": contentType,
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown usage card error";
    return NextResponse.json({ detail: message }, { status: 502 });
  }
}
