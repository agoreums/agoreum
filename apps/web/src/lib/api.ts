import { apiBaseUrl } from "@/lib/site";

/**
 * Typed client for the Agoreum API.
 *
 * Every response goes through the same error envelope the backend emits, so
 * callers get one error shape regardless of what failed.
 */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type ErrorEnvelope = {
  error?: { code?: string; message?: string; request_id?: string };
};

export async function apiFetch<T>(
  path: string,
  options: RequestInit & { accessToken?: string } = {},
): Promise<T> {
  const { accessToken, headers, ...rest } = options;

  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...headers,
    },
  });

  if (response.status === 204) {
    return undefined as T;
  }

  let body: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      // A non-JSON body means something upstream failed (a proxy error page,
      // for instance). Surface it as a generic failure rather than crashing.
      if (!response.ok) {
        throw new ApiError(
          "The server returned an unexpected response.",
          response.status,
          "unexpected_response",
        );
      }
    }
  }

  if (!response.ok) {
    const envelope = body as ErrorEnvelope | null;
    throw new ApiError(
      envelope?.error?.message ?? "The request failed.",
      response.status,
      envelope?.error?.code ?? "unknown_error",
      envelope?.error?.request_id,
    );
  }

  return body as T;
}

// --- Authentication ---------------------------------------------------------

export type AuthCapabilities = {
  siwe_domain: string;
  accepted_chain_ids: number[];
  contract_wallets_supported: boolean;
  nonce_ttl_seconds: number;
};

export type NonceResponse = {
  nonce: string;
  expires_at: string;
  message: string | null;
};

export type Tokens = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_at: string;
  refresh_expires_at: string;
};

export type UserProfile = {
  id: string;
  primary_address: string;
  username: string | null;
  display_name: string | null;
  bio: string | null;
  avatar_url: string | null;
  email: string | null;
  role: "user" | "admin";
  status: string;
  preferred_locale: string;
  created_at: string;
  last_seen_at: string | null;
};

export type SignInResponse = { user: UserProfile; tokens: Tokens };

export const authApi = {
  capabilities: () => apiFetch<AuthCapabilities>("/api/v1/auth/capabilities"),

  requestNonce: (address: string, chainId: number) =>
    apiFetch<NonceResponse>("/api/v1/auth/nonce", {
      method: "POST",
      body: JSON.stringify({ address, chain_id: chainId }),
    }),

  signIn: (payload: {
    message: string;
    signature: string;
    nonce: string;
    wallet_provider: string;
  }) =>
    apiFetch<SignInResponse>("/api/v1/auth/signin", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  refresh: (refreshToken: string) =>
    apiFetch<Tokens>("/api/v1/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
    }),

  logout: (accessToken: string, refreshToken?: string, allSessions = false) =>
    apiFetch<void>("/api/v1/auth/logout", {
      method: "POST",
      accessToken,
      body: JSON.stringify({
        refresh_token: refreshToken,
        all_sessions: allSessions,
      }),
    }),

  me: (accessToken: string) =>
    apiFetch<UserProfile>("/api/v1/auth/me", { accessToken }),
};

// --- Marketplace ------------------------------------------------------------

export type AgentSummary = {
  id: string;
  slug: string;
  name: string;
  avatar_url: string | null;
  verification_tier: "unverified" | "domain_verified" | "organization_verified";
  completed_orders: number;
  average_rating: number | null;
};

export type ServiceListItem = {
  id: string;
  slug: string;
  title: string;
  summary: string | null;
  pricing_model: "fixed" | "per_unit" | "hourly" | "negotiated";
  price: string | null;
  price_currency: string;
  price_unit: string | null;
  delivery_time_hours: number | null;
  tags: string[];
  completed_order_count: number;
  review_count: number;
  average_rating: number | null;
  agent: AgentSummary;
};

export type CategoryFacet = { slug: string; name: string; count: number };

export type ServiceSearchResults = {
  items: ServiceListItem[];
  total: number;
  limit: number;
  offset: number;
  query: string | null;
  sort: string;
  facets: CategoryFacet[] | null;
};

export type AgentSearchItem = {
  id: string;
  slug: string;
  name: string;
  tagline: string | null;
  avatar_url: string | null;
  verification_tier: AgentSummary["verification_tier"];
  verified_domain: string | null;
  completed_orders: number;
  review_count: number;
  average_rating: number | null;
  published_service_count: number;
};

export type AgentSearchResults = {
  items: AgentSearchItem[];
  total: number;
  limit: number;
  offset: number;
  query: string | null;
  sort: string;
};

export type Category = {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  parent_id: string | null;
  children?: Omit<Category, "children">[];
};

export type AgentProfile = AgentSearchItem & {
  description: string | null;
  website_url: string | null;
  capabilities: Record<string, unknown>;
  api_endpoint: string | null;
  payout_address: string | null;
  status: string;
  cancelled_orders: number;
  disputed_orders: number;
  published_at: string | null;
  last_active_at: string | null;
  created_at: string;
};

export type ServiceDetail = ServiceListItem & {
  description: string | null;
  status: string;
  min_quantity: number;
  max_quantity: number | null;
  auto_release_hours: number;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  order_count: number;
  published_at: string | null;
  created_at: string;
  category: { id: string; slug: string; name: string } | null;
};

export type FilterMetadata = {
  price: { min: string | null; max: string | null; currency: string };
  tags: { tag: string; count: number }[];
  sorts: string[];
  pricing_models: string[];
  verification_tiers: string[];
};

/** Drops empty values so they never reach the API as blank filters. */
function toQuery(params: Record<string, string | number | string[] | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "" || value === null) continue;
    if (Array.isArray(value)) {
      value.forEach((v) => v && search.append(key, v));
    } else {
      search.set(key, String(value));
    }
  }
  return search.toString();
}

export const marketplaceApi = {
  searchServices: (params: Record<string, string | number | string[] | undefined>) =>
    apiFetch<ServiceSearchResults>(
      `/api/v1/marketplace/services?${toQuery(params)}`,
    ),

  searchAgents: (params: Record<string, string | number | undefined>) =>
    apiFetch<AgentSearchResults>(`/api/v1/marketplace/agents?${toQuery(params)}`),

  filters: () => apiFetch<FilterMetadata>("/api/v1/marketplace/filters"),

  categories: () => apiFetch<Category[]>("/api/v1/categories"),

  agent: (slug: string) =>
    apiFetch<AgentProfile>(`/api/v1/agents/${encodeURIComponent(slug)}`),

  agentServices: (slug: string) =>
    apiFetch<ServiceDetail[]>(
      `/api/v1/agents/${encodeURIComponent(slug)}/services`,
    ),

  service: (agentSlug: string, serviceSlug: string) =>
    apiFetch<ServiceDetail>(
      `/api/v1/agents/${encodeURIComponent(agentSlug)}/services/${encodeURIComponent(serviceSlug)}`,
    ),
};

// --- Orders and payments ----------------------------------------------------

export type ChainStatus = {
  chain_id: number;
  network_name: string;
  escrow_configured: boolean;
  escrow_contract: string | null;
  token_address: string;
  token_symbol: string;
  confirmations_required: number;
  explorer_url: string;
  rpc_reachable: boolean;
  head_block: number | null;
  note: string | null;
};

export type OrderStatus =
  | "pending_payment" | "funded" | "in_progress" | "delivered"
  | "completed" | "disputed" | "cancelled" | "refunded" | "expired";

export type OrderSummary = {
  id: string;
  reference: string;
  status: OrderStatus;
  quantity: number;
  unit_price: string;
  subtotal: string;
  platform_fee: string;
  total_amount: string;
  currency: string;
  platform_fee_bps: number;
  created_at: string;
  funding_deadline: string | null;
  funded_at: string | null;
  delivered_at: string | null;
  auto_release_at: string | null;
  completed_at: string | null;
};

export type EscrowSummary = {
  status: string;
  chain_id: number;
  contract_address: string | null;
  onchain_escrow_id: string | null;
  token_symbol: string;
  amount: string;
  released_amount: string;
  refunded_amount: string;
  fee_amount: string;
  funded_at: string | null;
  released_at: string | null;
};

export type OrderDetail = OrderSummary & {
  requirements: string | null;
  delivery_note: string | null;
  buyer_id: string;
  provider_agent_id: string;
  service_id: string;
  escrow: EscrowSummary | null;
  transactions: {
    tx_hash: string;
    tx_type: string;
    status: string;
    amount: string | null;
    block_number: number | null;
    confirmations: number;
    explorer_url: string | null;
  }[];
};

export type PaymentInstructions = {
  order_id: string;
  order_reference: string;
  chain_id: number;
  network_name: string;
  escrow_contract: string;
  token_address: string;
  token_symbol: string;
  token_decimals: number;
  escrow_id: string;
  provider_address: string;
  amount: string;
  amount_base_units: string;
  delivery_window_seconds: number;
  auto_release_window_seconds: number;
  funding_deadline: string | null;
  explorer_url: string;
};

export const ordersApi = {
  chainStatus: () => apiFetch<ChainStatus>("/api/v1/chain/status"),

  create: (
    accessToken: string,
    body: { service_id: string; quantity?: number; requirements?: string },
  ) =>
    apiFetch<OrderDetail>("/api/v1/orders", {
      method: "POST",
      accessToken,
      body: JSON.stringify(body),
    }),

  mine: (accessToken: string) =>
    apiFetch<OrderSummary[]>("/api/v1/orders", { accessToken }),

  received: (accessToken: string) =>
    apiFetch<OrderSummary[]>("/api/v1/orders/received", { accessToken }),

  get: (accessToken: string, orderId: string) =>
    apiFetch<OrderDetail>(`/api/v1/orders/${orderId}`, { accessToken }),

  paymentInstructions: (accessToken: string, orderId: string) =>
    apiFetch<PaymentInstructions>(
      `/api/v1/orders/${orderId}/payment-instructions`,
      { accessToken },
    ),

  deliver: (accessToken: string, orderId: string, note?: string) =>
    apiFetch<OrderDetail>(`/api/v1/orders/${orderId}/deliver`, {
      method: "POST",
      accessToken,
      body: JSON.stringify({ delivery_note: note }),
    }),
};
