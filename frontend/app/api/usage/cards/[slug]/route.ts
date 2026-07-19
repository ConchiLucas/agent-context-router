import { NextResponse } from "next/server";

const API_BASE_URL =
  process.env.CONTEXT_ROUTER_INTERNAL_API_URL ??
  process.env.NEXT_PUBLIC_CONTEXT_ROUTER_API_URL ??
  "http://127.0.0.1:8000";

type RouteContext = {
  params: Promise<{
    slug: string;
  }>;
};

export async function GET(_request: Request, context: RouteContext) {
  const { slug } = await context.params;
  return proxyUsageCard(slug, "GET");
}

export async function PUT(request: Request, context: RouteContext) {
  const { slug } = await context.params;
  const requestBody = await request.text();
  return proxyUsageCard(slug, "PUT", requestBody || "{}");
}

export async function DELETE(_request: Request, context: RouteContext) {
  const { slug } = await context.params;
  return proxyUsageCard(slug, "DELETE");
}

async function proxyUsageCard(slug: string, method: "DELETE" | "GET" | "PUT", body?: string) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/usage/cards/${encodeURIComponent(slug)}`,
      {
        method,
        headers: body
          ? {
              "Content-Type": "application/json",
            }
          : undefined,
        body,
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
    const message = error instanceof Error ? error.message : "Unknown usage card error";
    return NextResponse.json({ detail: message }, { status: 502 });
  }
}
