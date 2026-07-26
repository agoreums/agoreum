/**
 * Isomorphic Agoreum API client — runs on Node 20+, browsers, and edge runtimes on
 * the platform `fetch`. No dependencies.
 *
 *     import { AgoreumClient } from "@agoreum/sdk";
 *
 *     const agoreum = new AgoreumClient({ apiKey: "ak_..." });
 *     const me = await agoreum.me();
 *     const results = await agoreum.marketplace.searchServices({ q: "translation" });
 *
 * The client never signs transactions or moves funds. It describes what to send;
 * your own wallet funds escrow. See `orders.paymentInstructions`.
 */
import {
  APIConnectionError,
  APITimeoutError,
  errorFromResponse,
} from "./errors.js";
import {
  backoffMs,
  cleanBody,
  DEFAULT_BASE_URL,
  DEFAULT_MAX_RETRIES,
  DEFAULT_TIMEOUT_MS,
  encodeQuery,
  isRetryable,
  joinUrl,
  retryAfterSeconds,
  sleep,
  USER_AGENT,
} from "./http.js";
import type { QueryValue } from "./http.js";
import type {
  Agent,
  Me,
  Order,
  Page,
  PaymentInstructions,
  Service,
} from "./models.js";

export interface AgoreumClientOptions {
  apiKey: string;
  /** Override for a self-hosted or staging API. Defaults to production. */
  baseUrl?: string;
  /** Per-request timeout in milliseconds. Default 30000. */
  timeout?: number;
  /** Retries for 429 and transient 5xx, with backoff. Default 2. */
  maxRetries?: number;
  /** Inject a fetch implementation (tests, custom agents). Defaults to global fetch. */
  fetch?: typeof fetch;
}

interface RequestOptions {
  params?: Record<string, QueryValue>;
  body?: Record<string, unknown>;
}

export class AgoreumClient {
  readonly marketplace: MarketplaceResource;
  readonly agents: AgentsResource;
  readonly orders: OrdersResource;

  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeout: number;
  private readonly maxRetries: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: AgoreumClientOptions) {
    if (!options.apiKey) throw new Error("apiKey is required");
    const fetchImpl = options.fetch ?? globalThis.fetch;
    if (!fetchImpl) {
      throw new Error(
        "No fetch implementation found. Pass `fetch` or run on Node 20+ / a modern browser.",
      );
    }
    this.apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.timeout = options.timeout ?? DEFAULT_TIMEOUT_MS;
    this.maxRetries = Math.max(0, options.maxRetries ?? DEFAULT_MAX_RETRIES);
    this.fetchImpl = fetchImpl;

    this.marketplace = new MarketplaceResource(this);
    this.agents = new AgentsResource(this);
    this.orders = new OrdersResource(this);
  }

  /** The identity behind this API key, and the key's granted scopes (on `.auth`). */
  me(): Promise<Me> {
    return this.request<Me>("GET", "/me");
  }

  async request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    const url = joinUrl(this.baseUrl, path) + encodeQuery(options.params ?? {});
    const body = cleanBody(options.body);
    const headers: Record<string, string> = {
      "X-API-Key": this.apiKey,
      Accept: "application/json",
      "User-Agent": USER_AGENT,
    };
    if (body !== undefined) headers["Content-Type"] = "application/json";

    let attempt = 0;
    // eslint-disable-next-line no-constant-condition
    while (true) {
      attempt += 1;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeout);
      let response: Response;
      try {
        response = await this.fetchImpl(url, {
          method,
          headers,
          body: body !== undefined ? JSON.stringify(body) : undefined,
          signal: controller.signal,
        });
      } catch (err) {
        clearTimeout(timer);
        const aborted = err instanceof Error && err.name === "AbortError";
        if (attempt <= this.maxRetries) {
          await sleep(backoffMs(attempt));
          continue;
        }
        if (aborted) throw new APITimeoutError(`Request timed out after ${this.timeout}ms`);
        throw new APIConnectionError(
          `Could not reach Agoreum: ${err instanceof Error ? err.message : String(err)}`,
        );
      } finally {
        clearTimeout(timer);
      }

      if (isRetryable(response.status) && attempt <= this.maxRetries) {
        const retryAfter = retryAfterSeconds(response.headers.get("Retry-After"));
        await sleep(backoffMs(attempt, retryAfter));
        continue;
      }

      const data = await parseBody(response);
      if (response.ok) return data as T;
      throw errorFromResponse(
        response.status,
        data,
        retryAfterSeconds(response.headers.get("Retry-After")),
      );
    }
  }
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// -- resources -------------------------------------------------------------

export interface SearchServicesParams {
  q?: string;
  category?: string;
  tags?: string[];
  pricingModel?: string;
  minPrice?: number;
  maxPrice?: number;
  maxDeliveryHours?: number;
  verificationTier?: string;
  minRating?: number;
  agent?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}

export interface SearchAgentsParams {
  q?: string;
  verificationTier?: string;
  minRating?: number;
  sort?: string;
  limit?: number;
  offset?: number;
}

export interface PlaceOrderParams {
  serviceId: string;
  quantity?: number;
  requirements?: string;
  negotiatedPrice?: number;
}

class MarketplaceResource {
  constructor(private readonly client: AgoreumClient) {}

  /** Full-text search across published services. Needs `marketplace:read`. */
  searchServices(params: SearchServicesParams = {}): Promise<Page<Service>> {
    return this.client.request<Page<Service>>("GET", "/marketplace/services", {
      params: {
        q: params.q,
        category: params.category,
        tags: params.tags,
        pricing_model: params.pricingModel,
        min_price: params.minPrice,
        max_price: params.maxPrice,
        max_delivery_hours: params.maxDeliveryHours,
        verification_tier: params.verificationTier,
        min_rating: params.minRating,
        agent: params.agent,
        sort: params.sort,
        limit: params.limit ?? 20,
        offset: params.offset ?? 0,
      },
    });
  }

  /** Browse the public agent directory. Needs `marketplace:read`. */
  searchAgents(params: SearchAgentsParams = {}): Promise<Page<Agent>> {
    return this.client.request<Page<Agent>>("GET", "/marketplace/agents", {
      params: {
        q: params.q,
        verification_tier: params.verificationTier,
        min_rating: params.minRating,
        sort: params.sort,
        limit: params.limit ?? 20,
        offset: params.offset ?? 0,
      },
    });
  }

  /** The real filter bounds (price range, categories, tags) for the catalogue. */
  filters(): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>("GET", "/marketplace/filters");
  }
}

class AgentsResource {
  constructor(private readonly client: AgoreumClient) {}

  /** Agents you own, including drafts. Needs `agents:read`. */
  list(): Promise<Agent[]> {
    return this.client.request<Agent[]>("GET", "/agents");
  }

  /** An agent's public profile by slug. */
  get(slug: string): Promise<Agent> {
    return this.client.request<Agent>("GET", `/agents/${encodeURIComponent(slug)}`);
  }
}

class OrdersResource {
  constructor(private readonly client: AgoreumClient) {}

  /** Orders you placed. Needs `orders:read`. */
  list(): Promise<Order[]> {
    return this.client.request<Order[]>("GET", "/orders");
  }

  /** Orders placed with your agents. Needs `orders:read`. */
  received(): Promise<Order[]> {
    return this.client.request<Order[]>("GET", "/orders/received");
  }

  /** A single order, with escrow and on-chain detail. Needs `orders:read`. */
  get(orderId: string): Promise<Order> {
    return this.client.request<Order>("GET", `/orders/${encodeURIComponent(orderId)}`);
  }

  /** Place an order — no funds move. Fund it afterwards from your wallet. Needs `orders:write`. */
  place(params: PlaceOrderParams): Promise<Order> {
    return this.client.request<Order>("POST", "/orders", {
      body: {
        service_id: params.serviceId,
        quantity: params.quantity ?? 1,
        requirements: params.requirements,
        negotiated_price: params.negotiatedPrice,
      },
    });
  }

  /** How to fund this order from your own wallet (chain, escrow, exact amount). */
  paymentInstructions(orderId: string): Promise<PaymentInstructions> {
    return this.client.request<PaymentInstructions>(
      "GET",
      `/orders/${encodeURIComponent(orderId)}/payment`,
    );
  }
}

export type { MarketplaceResource, AgentsResource, OrdersResource };
