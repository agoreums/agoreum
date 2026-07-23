import createMiddleware from "next-intl/middleware";

import { routing } from "@/i18n/routing";

/**
 * Locale negotiation proxy.
 *
 * Next 16 renamed the `middleware` file convention to `proxy`; the handler
 * contract is unchanged. This resolves the visitor's locale from the URL prefix,
 * then the `Accept-Language` header, and rewrites accordingly.
 */
export default createMiddleware(routing);

export const config = {
  // Run on every path except Next internals, the API routes, and anything that
  // looks like a static file. Keeping this tight matters: locale negotiation runs
  // on every request this matches.
  matcher: ["/((?!api|_next|_vercel|.*\..*).*)"],
};
