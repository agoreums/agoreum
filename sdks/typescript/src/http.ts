/** Pure transport helpers shared by the client, no I/O, easy to unit-test. */
import { VERSION } from "./version.js";

export const DEFAULT_BASE_URL = "https://agoreum.xyz/api/v1";
export const DEFAULT_TIMEOUT_MS = 30_000;
export const DEFAULT_MAX_RETRIES = 2;
export const USER_AGENT = `agoreum-typescript/${VERSION}`;

const RETRY_STATUSES = new Set([408, 429, 500, 502, 503, 504]);

export type QueryValue = string | number | boolean | Array<string | number> | null | undefined;

/** Build a query string, dropping null/undefined and repeating array keys. */
export function encodeQuery(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== null && item !== undefined) search.append(key, String(item));
      }
    } else {
      search.append(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

/** Strip null/undefined from a JSON body so optional fields are simply omitted. */
export function cleanBody(
  body: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined {
  if (!body) return undefined;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(body)) {
    if (value !== null && value !== undefined) out[key] = value;
  }
  return out;
}

export function isRetryable(status: number): boolean {
  return RETRY_STATUSES.has(status);
}

export function retryAfterSeconds(header: string | null): number | undefined {
  if (!header) return undefined;
  const seconds = Number(header);
  return Number.isFinite(seconds) ? Math.max(0, seconds) : undefined;
}

/** Backoff before an attempt (1-based): honour Retry-After, else jittered exponential. */
export function backoffMs(attempt: number, retryAfterSec?: number): number {
  if (retryAfterSec !== undefined) return retryAfterSec * 1000;
  const base = Math.min(20_000, 500 * 2 ** (attempt - 1));
  return Math.random() * base;
}

export function joinUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
