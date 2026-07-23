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
