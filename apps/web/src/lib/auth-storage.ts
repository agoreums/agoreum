import type { Tokens, UserProfile } from "@/lib/api";

/**
 * Client-side session storage.
 *
 * Tokens live in `sessionStorage`, not `localStorage`: the session ends when the
 * tab closes, which meaningfully limits exposure on a shared machine. Neither is
 * immune to XSS — the real defence there is the strict CSP in `next.config.ts`
 * and never rendering untrusted HTML.
 *
 * A cookie-based httpOnly session would be stronger still, but requires the API
 * and the site to share a registrable domain. That is planned for deployment,
 * when both sit behind agoreum.xyz; this module is the single place that would
 * need to change.
 */

const TOKENS_KEY = "agoreum.session.tokens";
const USER_KEY = "agoreum.session.user";

// Refresh this long before the access token actually expires, so an in-flight
// request never races the expiry.
export const REFRESH_MARGIN_MS = 60_000;

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function loadTokens(): Tokens | null {
  if (!isBrowser()) return null;
  try {
    const raw = window.sessionStorage.getItem(TOKENS_KEY);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  } catch {
    return null;
  }
}

export function saveTokens(tokens: Tokens): void {
  if (!isBrowser()) return;
  try {
    window.sessionStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
  } catch {
    // Storage can be unavailable (private mode, quota). The session simply does
    // not persist across a reload, which is a degradation rather than a failure.
  }
}

export function loadUser(): UserProfile | null {
  if (!isBrowser()) return null;
  try {
    const raw = window.sessionStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as UserProfile) : null;
  } catch {
    return null;
  }
}

export function saveUser(user: UserProfile): void {
  if (!isBrowser()) return;
  try {
    window.sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* see saveTokens */
  }
}

export function clearSession(): void {
  if (!isBrowser()) return;
  try {
    window.sessionStorage.removeItem(TOKENS_KEY);
    window.sessionStorage.removeItem(USER_KEY);
  } catch {
    /* nothing recoverable to do */
  }
}

export function millisecondsUntilRefresh(tokens: Tokens): number {
  const expiresAt = new Date(tokens.expires_at).getTime();
  return Math.max(0, expiresAt - Date.now() - REFRESH_MARGIN_MS);
}

export function isExpired(tokens: Tokens): boolean {
  return new Date(tokens.expires_at).getTime() <= Date.now();
}
