/**
 * Typed errors for the Agoreum SDK.
 *
 * Every API failure uses one envelope:
 *
 *     { "error": { "code": "...", "message": "...", "details": {...}, "request_id": "..." } }
 *
 * `errorFromResponse` maps that onto a specific class so callers can branch on the
 * error type (`instanceof NotFoundError`) or on `err.code` without parsing JSON.
 */

export interface ErrorOptions {
  status?: number;
  code?: string;
  details?: Record<string, unknown>;
  requestId?: string;
}

export class AgoreumError extends Error {
  readonly status?: number;
  readonly code?: string;
  readonly details: Record<string, unknown>;
  readonly requestId?: string;

  constructor(message: string, opts: ErrorOptions = {}) {
    super(message);
    this.name = new.target.name;
    this.status = opts.status;
    this.code = opts.code;
    this.details = opts.details ?? {};
    this.requestId = opts.requestId;
    // Restore the prototype chain when compiled down to ES5-era targets.
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/** The request never got a response (DNS, TCP, TLS, dropped connection). */
export class APIConnectionError extends AgoreumError {}

/** The request exceeded the configured timeout. */
export class APITimeoutError extends APIConnectionError {}

/** Base for every error that carries an HTTP status from the server. */
export class APIStatusError extends AgoreumError {}

/** 401 — the API key is missing, malformed, expired, or revoked. */
export class AuthenticationError extends APIStatusError {}

/** 403 — the key is valid but not allowed to do this. */
export class PermissionDeniedError extends APIStatusError {}

/** 403 with code `insufficient_scope` — the key lacks a required scope. */
export class InsufficientScopeError extends PermissionDeniedError {}

/** 404 — no such resource. */
export class NotFoundError extends APIStatusError {}

/** 409 — the request conflicts with the current state. */
export class ConflictError extends APIStatusError {}

/** 422 — well-formed but failed validation. */
export class UnprocessableEntityError extends APIStatusError {}

/** 429 — too many requests. `retryAfter` is seconds to wait, when supplied. */
export class RateLimitError extends APIStatusError {
  readonly retryAfter?: number;
  constructor(message: string, opts: ErrorOptions & { retryAfter?: number } = {}) {
    super(message, opts);
    this.retryAfter = opts.retryAfter;
  }
}

/** 503 — a feature is not configured or is temporarily down. */
export class ServiceUnavailableError extends APIStatusError {}

/** 5xx — the server failed to handle a valid request. */
export class ServerError extends APIStatusError {}

interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
}

export function errorFromResponse(
  status: number,
  body: unknown,
  retryAfter?: number,
): APIStatusError {
  let code: string | undefined;
  let message: string | undefined;
  let details: Record<string, unknown> | undefined;
  let requestId: string | undefined;

  const envelope = (body as ApiErrorBody | null | undefined)?.error;
  if (envelope) {
    code = envelope.code;
    message = envelope.message;
    details = envelope.details;
    requestId = envelope.request_id;
  }
  message ||= `HTTP ${status}`;

  const opts: ErrorOptions = { status, code, details, requestId };

  if (code === "insufficient_scope") return new InsufficientScopeError(message, opts);
  switch (status) {
    case 401:
      return new AuthenticationError(message, opts);
    case 403:
      return new PermissionDeniedError(message, opts);
    case 404:
      return new NotFoundError(message, opts);
    case 409:
      return new ConflictError(message, opts);
    case 422:
      return new UnprocessableEntityError(message, opts);
    case 429:
      return new RateLimitError(message, { ...opts, retryAfter });
    case 503:
      return new ServiceUnavailableError(message, opts);
    default:
      if (status >= 500) return new ServerError(message, opts);
      return new APIStatusError(message, opts);
  }
}
