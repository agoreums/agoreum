import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

import { contentSecurityPolicy } from "./src/lib/csp";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

/**
 * Static security headers. Strict-Transport-Security is set once at the edge by
 * nginx and is deliberately not duplicated here.
 */
const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
  },
  // Wallet SDKs (Coinbase Smart Wallet, WalletConnect) open a signer popup and
  // communicate with it through window.opener. `same-origin` would sever that and
  // break the connect flow; `same-origin-allow-popups` keeps this document
  // isolated while letting the popups it opens keep their opener.
  { key: "Cross-Origin-Opener-Policy", value: "same-origin-allow-popups" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Emits a minimal server bundle for the production Docker image.
  output: "standalone",

  typescript: {
    // Type errors must fail the build. Never set this to true.
    ignoreBuildErrors: false,
  },

  images: {
    formats: ["image/avif", "image/webp"],
  },

  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default withNextIntl(nextConfig);
