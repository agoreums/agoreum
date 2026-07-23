import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";

import { defaultLocale, routing } from "./routing";

/**
 * Resolves the message catalogue for the active request.
 *
 * Catalogues are imported per-locale so a build only ships the strings a given
 * page actually needs, rather than every language to every visitor.
 */
export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested)
    ? requested
    : defaultLocale;

  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
    // Fail loudly in development, stay quiet in production: a missing string
    // should block a release, not break a user's page.
    onError(error) {
      if (process.env.NODE_ENV === "development") {
        console.error(error);
      }
    },
  };
});
