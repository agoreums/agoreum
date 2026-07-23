import createMiddleware from "next-intl/middleware";
import type { NextRequest } from "next/server";

import { routing } from "@/i18n/routing";

const handleLocale = createMiddleware(routing);

/**
 * Locale negotiation proxy.
 *
 * Next 16 renamed the `middleware` file convention to `proxy`; the handler
 * contract is unchanged. This resolves the visitor's locale from the URL prefix,
 * then the `Accept-Language` header, and rewrites accordingly.
 *
 * Exported as an explicit function rather than `export default createMiddleware(...)`.
 * Next locates the entrypoint by statically analysing this file, and a bare call
 * expression is not recognised as a function export. The build still reports
 * success but ships no proxy at all, so unprefixed paths such as `/marketplace`
 * never reach a locale segment and return 404.
 */
export default function proxy(request: NextRequest) {
  return handleLocale(request);
}

export const config = {
  // Run on every path except Next internals, the API routes, and anything that
  // looks like a static file. Keeping this tight matters: locale negotiation runs
  // on every request this matches.
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)"],
};
