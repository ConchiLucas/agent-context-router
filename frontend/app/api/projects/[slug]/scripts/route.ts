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
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${encodeURIComponent(slug)}/scripts`,
    {
      headers: {
        Accept: "application/json",
      },
      cache: "no-store",
    },
  );
  return new Response(await response.text(), {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") ?? "application/json",
    },
  });
}
