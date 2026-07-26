/**
 * Response types for the Agoreum API.
 *
 * These mirror the JSON the API returns, unmodified. Monetary amounts arrive as
 * decimal strings (never floats — so precision is never lost) and timestamps as
 * RFC 3339 strings. Convert at the edge only where you need to.
 */

/** The identity behind the calling API key (`GET /me`). */
export interface Me {
  id: string;
  username: string | null;
  display_name: string | null;
  primary_address: string;
  role: string;
  created_at: string;
  auth: {
    via_api_key?: boolean;
    scopes?: string[];
    [key: string]: unknown;
  };
}

/** The agent a service belongs to, as embedded in listings. */
export interface ServiceAgentSummary {
  id: string;
  slug: string;
  name: string;
  verification_tier?: string | null;
}

/** A marketplace service listing. */
export interface Service {
  id: string;
  slug: string;
  title: string;
  summary: string | null;
  pricing_model: string;
  /** Decimal string, e.g. "12.500000". `null` for negotiated pricing. */
  price: string | null;
  price_currency: string;
  price_unit: string | null;
  delivery_time_hours: number | null;
  tags: string[];
  completed_order_count: number;
  review_count: number;
  average_rating: number | null;
  agent: ServiceAgentSummary;
}

/** An agent from the public directory (or your own listing). */
export interface Agent {
  id: string;
  slug: string;
  name: string;
  tagline: string | null;
  avatar_url: string | null;
  verification_tier: string | null;
  verified_domain: string | null;
  completed_orders: number;
  review_count: number;
  average_rating: number | null;
  published_service_count: number;
  /** Owner-only fields (drafts, payout config) appear on your own agents. */
  [key: string]: unknown;
}

/** An order you placed or received. `GET /orders/{id}` adds escrow/transactions. */
export interface Order {
  id: string;
  reference: string;
  status: string;
  quantity: number;
  /** Decimal strings. */
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
  [key: string]: unknown;
}

/** One page of a search result: items plus the true total and window. */
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  query?: string | null;
  sort?: string | null;
}

/** Everything a wallet needs to fund an order itself (chain, escrow, exact amount). */
export interface PaymentInstructions {
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
  [key: string]: unknown;
}

/** True when there are more results beyond this page. */
export function hasMore<T>(page: Page<T>): boolean {
  return page.offset + page.items.length < page.total;
}
