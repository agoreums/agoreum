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
  email_verified_at: string | null;
  role: "user" | "admin";
  status: string;
  preferred_locale: string;
  created_at: string;
  last_seen_at: string | null;
};

export type ProfileUpdate = {
  username?: string | null;
  display_name?: string | null;
  bio?: string | null;
  avatar_url?: string | null;
  email?: string | null;
  preferred_locale?: string;
};

export type SignInResponse = { user: UserProfile; tokens: Tokens };

export type WalletSummary = {
  id: string;
  address: string;
  chain_id: number;
  label: string | null;
  provider: string;
  verification_status: string;
  verified_at: string | null;
  is_payout: boolean;
};

export type SessionSummary = {
  id: string;
  address: string;
  chain_id: number;
  user_agent: string | null;
  created_at: string;
  last_used_at: string;
  expires_at: string;
};

export type EmailVerificationStatus = {
  /** False when the deployment cannot send, so the interface never promises a message that is not coming. */
  sent: boolean;
  detail: string;
};

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

  wallets: (accessToken: string) =>
    apiFetch<WalletSummary[]>("/api/v1/auth/me/wallets", { accessToken }),

  sessions: (accessToken: string) =>
    apiFetch<SessionSummary[]>("/api/v1/auth/me/sessions", { accessToken }),

  updateProfile: (accessToken: string, body: ProfileUpdate) =>
    apiFetch<UserProfile>("/api/v1/auth/me", {
      method: "PATCH",
      accessToken,
      body: JSON.stringify(body),
    }),

  /** Ask for a fresh confirmation link. Rate limited server side to three an hour. */
  requestEmailVerification: (accessToken: string) =>
    apiFetch<EmailVerificationStatus>("/api/v1/auth/me/email/verify", {
      method: "POST",
      accessToken,
    }),

  /**
   * Spend a confirmation token.
   *
   * Deliberately takes no access token. The token from the message is the proof,
   * so the link works in whichever browser the inbox happens to open it in,
   * signed in or not.
   */
  confirmEmail: (token: string) =>
    apiFetch<UserProfile>("/api/v1/auth/me/email/confirm", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  suspend: (accessToken: string) =>
    apiFetch<void>("/api/v1/auth/me/suspend", {
      method: "POST",
      accessToken,
    }),
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

export type AgentCapabilities = {
  skills: string[];
  input_modalities: string[];
  output_modalities: string[];
  protocols: string[];
  languages: string[];
};

export type AgentProfile = AgentSearchItem & {
  description: string | null;
  website_url: string | null;
  capabilities: AgentCapabilities;
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

// --- Dashboards, reviews and notifications ----------------------------------

export type BuyerDashboard = {
  active_orders: number;
  completed_orders: number;
  disputed_orders: number;
  total_spent: string;
  currency: string;
  pending_payment: number;
  awaiting_review: number;
  recent_orders: {
    id: string;
    reference: string;
    status: OrderStatus;
    total_amount: string;
    currency: string;
    created_at: string;
  }[];
};

export type ProviderDashboard = {
  agents: number;
  published_agents: number;
  published_services: number;
  active_orders: number;
  completed_orders: number;
  /** Null until something has actually settled, not a measured zero. */
  total_earned: string | null;
  currency: string;
  average_rating: number | null;
  review_count: number;
  awaiting_action: number;
  recent_orders: BuyerDashboard["recent_orders"];
};

export type ReputationReport = {
  agent_id: string;
  agent_slug: string;
  /** Null when there is too little settled history for a score to mean anything. */
  score: string | null;
  algorithm_version: string;
  computed_at: string | null;
  completed_orders: number;
  cancelled_orders: number;
  disputed_orders: number;
  disputes_lost: number;
  review_count: number;
  average_rating: number | null;
  total_volume: string;
  volume_currency: string;
  median_delivery_hours: string | null;
  on_time_delivery_rate: string | null;
  note: string | null;
};

export type NotificationItem = {
  id: string;
  category: string;
  event_type: string;
  title: string;
  body: string | null;
  action_url: string | null;
  read_at: string | null;
  created_at: string;
  deliveries: { channel: string; status: string; last_error: string | null }[];
};

export type NotificationList = {
  items: NotificationItem[];
  total: number;
  unread: number;
  limit: number;
  offset: number;
};

export const dashboardApi = {
  buyer: (accessToken: string) =>
    apiFetch<BuyerDashboard>("/api/v1/dashboard/buyer", { accessToken }),

  provider: (accessToken: string) =>
    apiFetch<ProviderDashboard>("/api/v1/dashboard/provider", { accessToken }),
};

export type CreatorAnalytics = {
  window_days: number;
  // Null when the view data source is unavailable, never a fabricated zero.
  views: number | null;
  views_series: { date: string; views: number }[] | null;
  purchases: number;
  revenue: string;
  currency: string;
  repeat_customers: number;
  conversion_rate: number | null;
  revenue_series: { date: string; revenue: string }[];
  /** Committed but not earned. Reported apart from revenue, never added to it. */
  pipeline: {
    active_orders: number;
    active_value: string;
    disputed_orders: number;
    disputed_value: string;
    refunded_orders: number;
    refunded_value: string;
  };
  /** The same window immediately before this one. */
  trend: {
    purchases: number;
    revenue: string;
    // Null when the previous period was zero: growth from nothing has no
    // percentage, and rendering one would look like a measurement.
    purchases_change_pct: number | null;
    revenue_change_pct: number | null;
  };
};

export type BuyerAnalytics = {
  window_days: number;
  currency: string;
  orders: number;
  /** Total charged, including the platform fee, since that is what was paid. */
  spend: string;
  active_orders: number;
  active_value: string;
  disputed_orders: number;
  providers_used: number;
};

export const analyticsApi = {
  me: (accessToken: string, windowDays = 30) =>
    apiFetch<CreatorAnalytics>(
      `/api/v1/analytics/me?window_days=${windowDays}`,
      { accessToken },
    ),

  purchases: (accessToken: string, windowDays = 30) =>
    apiFetch<BuyerAnalytics>(
      `/api/v1/analytics/me/purchases?window_days=${windowDays}`,
      { accessToken },
    ),
};

export const reputationApi = {
  forAgent: (slug: string) =>
    apiFetch<ReputationReport>(
      `/api/v1/agents/${encodeURIComponent(slug)}/reputation`,
    ),
};

export type NotificationChannel = "in_app" | "email";
export type NotificationCategory =
  | "order" | "payment" | "message" | "reputation" | "security" | "system";

export type NotificationPreference = {
  category: NotificationCategory;
  channel: NotificationChannel;
  enabled: boolean;
};

export type EmailStatus = {
  enabled: boolean;
  reason: string | null;
  from_address: string;
};

export const notificationsApi = {
  list: (accessToken: string, unreadOnly = false) =>
    apiFetch<NotificationList>(
      `/api/v1/notifications?unread_only=${unreadOnly}`,
      { accessToken },
    ),

  markRead: (accessToken: string, id: string) =>
    apiFetch<NotificationItem>(`/api/v1/notifications/${id}/read`, {
      method: "POST",
      accessToken,
    }),

  markAllRead: (accessToken: string) =>
    apiFetch<{ marked: number }>("/api/v1/notifications/read-all", {
      method: "POST",
      accessToken,
    }),

  preferences: (accessToken: string) =>
    apiFetch<NotificationPreference[]>("/api/v1/notifications/preferences", {
      accessToken,
    }),

  setPreference: (accessToken: string, body: NotificationPreference) =>
    apiFetch<NotificationPreference>("/api/v1/notifications/preferences", {
      method: "PUT",
      accessToken,
      body: JSON.stringify(body),
    }),

  emailStatus: () =>
    apiFetch<EmailStatus>("/api/v1/notifications/email-status"),
};

// --- API keys ---------------------------------------------------------------

export type ApiKeyScope = {
  scope: string;
  description: string;
};

export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
};

/** Only ever returned once, at creation: it carries the plaintext `token`. */
export type ApiKeyCreated = ApiKey & { token: string };

/**
 * API keys and webhooks belong to an organization. Passing an org slug scopes
 * the call to that org; omitting it uses the caller's personal organization, so
 * a solo creator never has to think about orgs.
 */
function orgQuery(orgSlug?: string): string {
  return orgSlug ? `?org=${encodeURIComponent(orgSlug)}` : "";
}

export const apiKeysApi = {
  scopes: () =>
    apiFetch<{ scopes: ApiKeyScope[] }>("/api/v1/api-keys/scopes"),

  list: (accessToken: string, orgSlug?: string) =>
    apiFetch<{ items: ApiKey[]; total: number }>(
      `/api/v1/api-keys${orgQuery(orgSlug)}`,
      { accessToken },
    ),

  create: (
    accessToken: string,
    body: { name: string; scopes: string[]; expires_in_days?: number | null },
    orgSlug?: string,
  ) =>
    apiFetch<ApiKeyCreated>(`/api/v1/api-keys${orgQuery(orgSlug)}`, {
      method: "POST",
      accessToken,
      body: JSON.stringify(body),
    }),

  revoke: (accessToken: string, id: string, orgSlug?: string) =>
    apiFetch<void>(`/api/v1/api-keys/${id}${orgQuery(orgSlug)}`, {
      method: "DELETE",
      accessToken,
    }),
};

// --- Webhooks ---------------------------------------------------------------

export type WebhookEvent = {
  event: string;
  description: string;
};

export type WebhookEndpoint = {
  id: string;
  url: string;
  description: string | null;
  events: string[];
  last_delivery_at: string | null;
  last_success_at: string | null;
  revoked_at: string | null;
  created_at: string;
};

/** Only ever returned once, at creation: it carries the plaintext signing `secret`. */
export type WebhookEndpointCreated = WebhookEndpoint & { secret: string };

export type WebhookDelivery = {
  id: string;
  event_type: string;
  event_id: string;
  status: string;
  attempts: number;
  max_attempts: number;
  last_status_code: number | null;
  last_error: string | null;
  last_duration_ms: number | null;
  next_attempt_at: string;
  delivered_at: string | null;
  created_at: string;
};

export const webhooksApi = {
  events: () => apiFetch<{ events: WebhookEvent[] }>("/api/v1/webhooks/events"),

  list: (accessToken: string, orgSlug?: string) =>
    apiFetch<{ items: WebhookEndpoint[]; total: number }>(
      `/api/v1/webhooks${orgQuery(orgSlug)}`,
      { accessToken },
    ),

  create: (
    accessToken: string,
    body: { url: string; events: string[]; description?: string | null },
    orgSlug?: string,
  ) =>
    apiFetch<WebhookEndpointCreated>(`/api/v1/webhooks${orgQuery(orgSlug)}`, {
      method: "POST",
      accessToken,
      body: JSON.stringify(body),
    }),

  revoke: (accessToken: string, id: string, orgSlug?: string) =>
    apiFetch<void>(`/api/v1/webhooks/${id}${orgQuery(orgSlug)}`, {
      method: "DELETE",
      accessToken,
    }),

  deliveries: (accessToken: string, id: string, orgSlug?: string) =>
    apiFetch<WebhookDelivery[]>(
      `/api/v1/webhooks/${id}/deliveries${orgQuery(orgSlug)}`,
      { accessToken },
    ),
};

// --- Organizations ----------------------------------------------------------

export type OrgKind = "personal" | "team";
export type OrgRole = "member" | "admin" | "owner";

export type Organization = {
  id: string;
  slug: string;
  name: string;
  kind: OrgKind;
  /** The requesting member's own role in this org. */
  role: OrgRole;
  member_count: number;
};

export type OrgMember = {
  user_id: string;
  role: OrgRole;
  username: string | null;
  display_name: string | null;
  primary_address: string;
  joined_at: string;
};

export type OrgInvitation = {
  id: string;
  org_id: string;
  org_slug: string;
  org_name: string;
  role: OrgRole;
  invited_user_id: string;
  expires_at: string;
  created_at: string;
};

export const orgsApi = {
  list: (accessToken: string) =>
    apiFetch<Organization[]>("/api/v1/orgs", { accessToken }),

  create: (accessToken: string, body: { slug: string; name: string }) =>
    apiFetch<Organization>("/api/v1/orgs", {
      method: "POST",
      accessToken,
      body: JSON.stringify(body),
    }),

  members: (accessToken: string, slug: string) =>
    apiFetch<OrgMember[]>(
      `/api/v1/orgs/${encodeURIComponent(slug)}/members`,
      { accessToken },
    ),

  /**
   * Offer membership. Replaces adding somebody directly, which put an account
   * into an organization it never agreed to join.
   */
  inviteMember: (
    accessToken: string,
    slug: string,
    body: { address: string; role: OrgRole },
  ) =>
    apiFetch<OrgInvitation>(
      `/api/v1/orgs/${encodeURIComponent(slug)}/invitations`,
      { method: "POST", accessToken, body: JSON.stringify(body) },
    ),

  invitations: (accessToken: string, slug: string) =>
    apiFetch<OrgInvitation[]>(
      `/api/v1/orgs/${encodeURIComponent(slug)}/invitations`,
      { accessToken },
    ),

  revokeInvitation: (accessToken: string, slug: string, invitationId: string) =>
    apiFetch<void>(
      `/api/v1/orgs/${encodeURIComponent(slug)}/invitations/${invitationId}`,
      { method: "DELETE", accessToken },
    ),

  /** Invitations waiting for the signed-in account to answer. */
  myInvitations: (accessToken: string) =>
    apiFetch<OrgInvitation[]>("/api/v1/orgs/invitations/mine", { accessToken }),

  acceptInvitation: (accessToken: string, invitationId: string) =>
    apiFetch<Organization>(
      `/api/v1/orgs/invitations/${invitationId}/accept`,
      { method: "POST", accessToken },
    ),

  declineInvitation: (accessToken: string, invitationId: string) =>
    apiFetch<void>(
      `/api/v1/orgs/invitations/${invitationId}/decline`,
      { method: "POST", accessToken },
    ),

  updateMember: (
    accessToken: string,
    slug: string,
    userId: string,
    role: OrgRole,
  ) =>
    apiFetch<OrgMember>(
      `/api/v1/orgs/${encodeURIComponent(slug)}/members/${userId}`,
      { method: "PATCH", accessToken, body: JSON.stringify({ role }) },
    ),

  removeMember: (accessToken: string, slug: string, userId: string) =>
    apiFetch<void>(
      `/api/v1/orgs/${encodeURIComponent(slug)}/members/${userId}`,
      { method: "DELETE", accessToken },
    ),

  leave: (accessToken: string, slug: string) =>
    apiFetch<void>(`/api/v1/orgs/${encodeURIComponent(slug)}/leave`, {
      method: "POST",
      accessToken,
    }),
};

// --- Subscriptions ----------------------------------------------------------

export type SubscriptionPlan = {
  plan_id: number;
  name: string;
  description: string | null;
  tier: string;
  interval: "monthly" | "yearly";
  token_symbol: string;
  price: string;
  period_seconds: number;
  active: boolean;
};

export type SubscriptionStatus = {
  plan_id: number;
  tier: string;
  status: "active" | "cancelled" | "expired";
  subscriber_address: string;
  current_period_start: string;
  current_period_end: string;
  auto_renew_cancelled: boolean;
  plan: SubscriptionPlan | null;
};

export type SubscriptionPayment = {
  id: string;
  tx_hash: string;
  plan_id: number;
  amount: string;
  token_symbol: string;
  period_start: string;
  period_end: string;
  block_number: number;
  created_at: string;
};

export type SubscribeInstructions = {
  chain_id: number;
  subscription_contract: string;
  plan_id: number;
  token_address: string;
  token_symbol: string;
  token_decimals: number;
  price: string;
  price_base_units: string;
  max_price_base_units: string;
  note: string;
};

export const subscriptionsApi = {
  plans: () => apiFetch<SubscriptionPlan[]>("/api/v1/subscriptions/plans"),

  mine: (accessToken: string) =>
    apiFetch<SubscriptionStatus[]>("/api/v1/subscriptions/me", { accessToken }),

  payments: (accessToken: string) =>
    apiFetch<SubscriptionPayment[]>("/api/v1/subscriptions/me/payments", {
      accessToken,
    }),

  instructions: (planId: number) =>
    apiFetch<SubscribeInstructions>(
      `/api/v1/subscriptions/plans/${planId}/instructions`,
    ),
};
