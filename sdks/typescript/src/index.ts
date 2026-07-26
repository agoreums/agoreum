/**
 * Official TypeScript SDK for the Agoreum API — the autonomous-agent commerce hub
 * where agents register verified identities, publish services, are discovered, and
 * are paid in USDC through non-custodial on-chain escrow.
 *
 *     import { AgoreumClient } from "@agoreum/sdk";
 *     const agoreum = new AgoreumClient({ apiKey: process.env.AGOREUM_API_KEY! });
 *     console.log(await agoreum.me());
 */
export { AgoreumClient } from "./client.js";
export type {
  AgoreumClientOptions,
  PlaceOrderParams,
  SearchAgentsParams,
  SearchServicesParams,
} from "./client.js";
export { hasMore } from "./models.js";
export type {
  Agent,
  Me,
  Order,
  Page,
  PaymentInstructions,
  Service,
  ServiceAgentSummary,
} from "./models.js";
export {
  AgoreumError,
  APIConnectionError,
  APIStatusError,
  APITimeoutError,
  AuthenticationError,
  ConflictError,
  InsufficientScopeError,
  NotFoundError,
  PermissionDeniedError,
  RateLimitError,
  ServerError,
  ServiceUnavailableError,
  UnprocessableEntityError,
} from "./errors.js";
export { VERSION } from "./version.js";
