/**
 * Content Security Policy.
 *
 * The previous policy was `script-src 'self'` with no `'unsafe-inline'` and no
 * nonce. That silently blocked Next's own inline hydration scripts, so React
 * never hydrated and every interactive control — wallet connect, the locale
 * switcher, the mobile menu — did nothing. The SSR HTML still rendered, which is
 * why the site looked fine until you clicked.
 *
 * `'unsafe-inline'` restores it. A nonce would be stricter, but a nonce must be
 * unique per request and therefore forces every page to render dynamically and
 * escape the CDN cache — Next literally cannot apply a per-request nonce to a
 * statically generated, Cloudflare-cached page, so hydration would break again
 * on exactly the pages we serve fastest. Given the other directives stay tight
 * (no `unsafe-eval`, `object-src 'none'`, `base-uri 'self'`,
 * `frame-ancestors 'none'`, an explicit `connect-src`) and React escapes all
 * output, this is the correct trade for a static, cached front end.
 */

/** Wallet SDKs reach these at runtime; without them the connectors fail silently. */
const WALLET_CONNECT_SRC = [
  "https://sepolia.base.org",
  "https://mainnet.base.org",
  "https://*.base.org",
  "https://*.coinbase.com",
  "https://*.cbwallet.com",
  "wss://*.coinbase.com",
  "https://*.walletconnect.com",
  "https://*.walletconnect.org",
  "https://*.reown.com",
  "wss://*.walletconnect.com",
  "wss://*.walletconnect.org",
  // Reown AppKit fetches wallet metadata and the WalletConnect relay from these.
  "https://api.web3modal.org",
  "https://*.web3modal.org",
  "https://pulse.walletconnect.org",
];

/** Coinbase Smart Wallet renders its signer in a frame at keys.coinbase.com. */
const WALLET_FRAME_SRC = ["https://keys.coinbase.com", "https://*.walletconnect.org"];

const isDev = process.env.NODE_ENV === "development";

export const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  "img-src 'self' data: blob: https:",
  // Reown AppKit pulls its KHTeka webfont from fonts.reown.com; without it the
  // wallet modal logs a CSP violation on every page and falls back to a system font.
  "font-src 'self' data: https://fonts.reown.com",
  "style-src 'self' 'unsafe-inline'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  ["connect-src 'self'", "https://api.agoreum.xyz", ...WALLET_CONNECT_SRC].join(" "),
  ["frame-src 'self'", ...WALLET_FRAME_SRC].join(" "),
  "upgrade-insecure-requests",
].join("; ");
