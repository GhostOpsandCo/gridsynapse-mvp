import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const DEFAULT_API_ORIGIN = process.env.VERCEL
  ? "https://gridsynapse-api.vercel.app"
  : "http://127.0.0.1:8080";

const API_ORIGIN = (
  process.env.GRIDSYNAPSE_API_ORIGIN ?? DEFAULT_API_ORIGIN
).replace(/\/$/, "");

const RESPONSE_HEADERS = [
  "cache-control",
  "content-disposition",
  "content-type",
] as const;

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const upstreamUrl = new URL(`${API_ORIGIN}/${path.map(encodeURIComponent).join("/")}`);
  upstreamUrl.search = request.nextUrl.search;

  const headers = new Headers();
  for (const name of ["accept", "content-type"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  const bypassSecret = process.env.GRIDSYNAPSE_API_BYPASS_SECRET;
  if (bypassSecret) {
    headers.set("x-vercel-protection-bypass", bypassSecret);
  }

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const response = await fetch(upstreamUrl, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    cache: "no-store",
    redirect: "manual",
  });

  const responseHeaders = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = response.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }

  return new Response(response.body, {
    status: response.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
