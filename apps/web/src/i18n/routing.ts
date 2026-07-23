import { defineRouting } from "next-intl/routing";

/**
 * Supported locales.
 *
 * Adding a locale requires exactly two changes: append it here and add the
 * matching `src/messages/<locale>.json`. Everything else — routing, the locale
 * switcher, `hreflang` alternates, and the sitemap — derives from this list, so
 * translations can never drift out of sync with the routes that serve them.
 */
export const locales = ["en", "es", "fr", "de", "pt", "ja", "ko", "zh"] as const;

export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = "en";

/** Human-readable names, written in each language as a native speaker sees it. */
export const localeNames: Record<Locale, string> = {
  en: "English",
  es: "Español",
  fr: "Français",
  de: "Deutsch",
  pt: "Português",
  ja: "日本語",
  ko: "한국어",
  zh: "中文",
};

/** BCP-47 tags for `hreflang` and `Content-Language`. */
export const localeHreflang: Record<Locale, string> = {
  en: "en",
  es: "es",
  fr: "fr",
  de: "de",
  pt: "pt",
  ja: "ja",
  ko: "ko",
  zh: "zh-Hans",
};

/** Locales that render right-to-left. None today; the plumbing is ready. */
export const rtlLocales: readonly Locale[] = [];

export function getDirection(locale: Locale): "ltr" | "rtl" {
  return rtlLocales.includes(locale) ? "rtl" : "ltr";
}

export const routing = defineRouting({
  locales,
  defaultLocale,
  // Every locale carries an explicit prefix, including the default: `/en/…`,
  // `/es/…`. The alternative ("as-needed") leaves the default locale unprefixed,
  // which means one URL shape has to be rewritten while every other is
  // redirected — a distinction that produced a redirect loop on `/` here.
  //
  // Always-prefixing costs a slightly longer English URL and buys unambiguous,
  // individually cacheable routes with no special case anywhere in the codebase.
  // SEO is unaffected: canonical, hreflang and x-default are all emitted
  // explicitly, and `/` redirects to the negotiated locale.
  localePrefix: "always",
  localeDetection: true,
});
