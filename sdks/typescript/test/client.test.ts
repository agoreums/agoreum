import { describe, expect, it, vi } from "vitest";

import {
  AgoreumClient,
  AuthenticationError,
  InsufficientScopeError,
  NotFoundError,
  RateLimitError,
  hasMore,
} from "../src/index.js";

const BASE = "https://agoreum.xyz/api/v1";

const ME = {
  id: "11111111-1111-1111-1111-111111111111",
  username: "acme",
  display_name: "Acme Labs",
  primary_address: "0xf688A25DB028dE3FfC670c0C5A79ee1A5E9BD90A",
  role: "user",
  created_at: "2026-07-01T12:00:00Z",
  auth: { via_api_key: true, scopes: ["marketplace:read", "orders:read"] },
};

const SERVICE_PAGE = {
  items: [
    {
      id: "22222222-2222-2222-2222-222222222222",
      slug: "fast-translation",
      title: "Fast Translation",
      summary: "Human-quality translation in minutes.",
      pricing_model: "fixed",
      price: "12.500000",
      price_currency: "USDC",
      price_unit: "per document",
      delivery_time_hours: 24,
      tags: ["translation", "localization"],
      completed_order_count: 42,
      review_count: 30,
      average_rating: 4.8,
      agent: {
        id: "33333333-3333-3333-3333-333333333333",
        slug: "acme-translate",
        name: "Acme Translate",
        verification_tier: "domain",
      },
    },
  ],
  total: 1,
  limit: 20,
  offset: 0,
  query: "translation",
  sort: "relevance",
};

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(body === null ? "" : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function envelope(code: string, message: string, extra: Record<string, unknown> = {}) {
  return { error: { code, message, ...extra } };
}

function clientWith(fetchImpl: typeof fetch, maxRetries = 2) {
  return new AgoreumClient({ apiKey: "ak_test", fetch: fetchImpl, maxRetries });
}

// A fetch-shaped mock so `.mock.calls[i]` is typed as [url, init?] rather than [].
function fetchMockOf(impl: (url: string, init?: RequestInit) => Promise<Response>) {
  return vi.fn(impl);
}

describe("AgoreumClient", () => {
  it("sends the API key and parses /me", async () => {
    const fetchMock = fetchMockOf(async () => jsonResponse(200, ME));
    const client = clientWith(fetchMock as unknown as typeof fetch);
    const me = await client.me();

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe(`${BASE}/me`);
    expect((init as RequestInit).headers).toMatchObject({ "X-API-Key": "ak_test" });
    expect(me.username).toBe("acme");
    expect(me.auth.scopes).toEqual(["marketplace:read", "orders:read"]);
  });

  it("encodes search params (repeated arrays) and parses the page", async () => {
    const fetchMock = fetchMockOf(async () => jsonResponse(200, SERVICE_PAGE));
    const client = clientWith(fetchMock as unknown as typeof fetch);
    const page = await client.marketplace.searchServices({
      q: "translation",
      tags: ["translation", "localization"],
      minRating: 4.0,
    });

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get("q")).toBe("translation");
    expect(url.searchParams.getAll("tags")).toEqual(["translation", "localization"]);
    expect(url.searchParams.get("min_rating")).toBe("4");

    expect(page.total).toBe(1);
    expect(hasMore(page)).toBe(false);
    expect(page.items[0]!.price).toBe("12.500000");
    expect(page.items[0]!.agent.slug).toBe("acme-translate");
  });

  it("omits null body fields when placing an order", async () => {
    const order = {
      id: "44444444-4444-4444-4444-444444444444",
      reference: "AGO-0001",
      status: "pending_payment",
      quantity: 2,
      unit_price: "12.500000",
      subtotal: "25.000000",
      platform_fee: "0.500000",
      total_amount: "25.500000",
      currency: "USDC",
      platform_fee_bps: 200,
      created_at: "2026-07-26T10:00:00Z",
    };
    const fetchMock = fetchMockOf(async () => jsonResponse(201, order));
    const client = clientWith(fetchMock as unknown as typeof fetch);
    const placed = await client.orders.place({ serviceId: "svc-1", quantity: 2 });

    const body = JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string);
    expect(body).toEqual({ service_id: "svc-1", quantity: 2 });
    expect(body).not.toHaveProperty("negotiated_price");
    expect(placed.reference).toBe("AGO-0001");
  });

  it("maps the error envelope to typed exceptions", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(401, envelope("unauthenticated", "Provide an API key.")),
    );
    const client = clientWith(fetchMock as unknown as typeof fetch);
    await expect(client.me()).rejects.toBeInstanceOf(AuthenticationError);
  });

  it("raises NotFoundError on 404", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(404, envelope("not_found", "No such agent.")));
    const client = clientWith(fetchMock as unknown as typeof fetch);
    await expect(client.agents.get("ghost")).rejects.toBeInstanceOf(NotFoundError);
  });

  it("distinguishes insufficient_scope with details", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(
        403,
        envelope("insufficient_scope", "Missing scope orders:read.", {
          details: { missing: ["orders:read"] },
        }),
      ),
    );
    const client = clientWith(fetchMock as unknown as typeof fetch);
    try {
      await client.orders.list();
      expect.unreachable("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(InsufficientScopeError);
      expect((err as InsufficientScopeError).details).toEqual({ missing: ["orders:read"] });
    }
  });

  it("retries 429 then succeeds", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(429, envelope("rate_limited", "Slow down."), { "Retry-After": "0" }),
      )
      .mockResolvedValueOnce(jsonResponse(200, ME));
    const client = clientWith(fetchMock as unknown as typeof fetch, 2);
    const me = await client.me();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(me.username).toBe("acme");
  });

  it("gives up after max retries", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(429, envelope("rate_limited", "Slow down."), { "Retry-After": "0" }),
    );
    const client = clientWith(fetchMock as unknown as typeof fetch, 1);
    await expect(client.me()).rejects.toBeInstanceOf(RateLimitError);
    expect(fetchMock).toHaveBeenCalledTimes(2); // initial + 1 retry
  });

  it("requires an API key", () => {
    expect(() => new AgoreumClient({ apiKey: "" })).toThrow();
  });
});
