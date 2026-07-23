import { NextResponse } from "next/server";

import { apiBaseUrl } from "@/lib/site";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const UPSTREAM_TIMEOUT_MS = 3000;

/**
 * Frontend health endpoint.
 *
 * Reports whether this Next.js process is serving *and* whether it can reach the
 * API. The upstream result is reported truthfully: if the API is unreachable this
 * returns 503 rather than claiming health the process cannot vouch for.
 */
export async function GET() {
  const startedAt = performance.now();
  let api: { status: "ok" | "down"; latencyMs?: number; error?: string };

  try {
    const response = await fetch(`${apiBaseUrl}/api/v1/health/live`, {
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
      cache: "no-store",
    });
    api = response.ok
      ? { status: "ok", latencyMs: Math.round(performance.now() - startedAt) }
      : { status: "down", error: `upstream responded ${response.status}` };
  } catch (error) {
    api = {
      status: "down",
      error: error instanceof Error ? error.name : "unknown error",
    };
  }

  const healthy = api.status === "ok";

  return NextResponse.json(
    {
      status: healthy ? "ok" : "down",
      service: "agoreum-web",
      components: { api },
    },
    {
      status: healthy ? 200 : 503,
      headers: { "Cache-Control": "no-store" },
    },
  );
}
