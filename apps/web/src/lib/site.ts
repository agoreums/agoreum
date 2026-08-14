import { localeHreflang, locales, routing, type Locale } from "@/i18n/routing";

/**
 * Canonical site constants.
 *
 * Anything that appears in metadata, structured data, or the footer is defined
 * once here so the site, the manifest, and the social cards can never disagree.
 */

export const siteConfig = {
  name: "Agoreum",
  shortName: "Agoreum",
  domain: "agoreum.xyz",
  url: process.env.NEXT_PUBLIC_APP_URL ?? "https://agoreum.xyz",
  supportEmail: "support@agoreum.xyz",
  themeColor: "#0A0A12",
  social: {
    x: "https://x.com/agoreum",
    discord: "https://discord.gg/8AcrcjYfuS",
    reddit: "https://www.reddit.com/r/Agoreum",
    telegram: "https://t.me/agoreum",
    instagram: "https://instagram.com/agoreum",
    // The org page, not the repo: the repo is private, so a repo link 404s for
    // every visitor. The org is public and keeps working if repos are opened later.
    github: "https://github.com/agoreums",
  },
  chain: {
    name: "Base",
    id: 8453,
    currency: "USDC",
  },
} as const;

export const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Absolute URL builder, metadata and structured data must never emit relative URLs. */
export function absoluteUrl(path = "/"): string {
  const base = siteConfig.url.replace(/\/$/, "");
  return path.startsWith("/") ? `${base}${path}` : `${base}/${path}`;
}

/**
 * The `alternates` block for a page, in every locale.
 *
 * Next merges page metadata over layout metadata field by field, so a page that
 * sets `alternates` replaces the layout's entirely. Pages were setting only a
 * canonical, and a locale-less one, which had two consequences on every page
 * except the locale root.
 *
 * All nine locales advertised the *same* canonical URL, which tells a search
 * engine they are duplicates of one page, so eight of the nine would be dropped
 * and the whole point of shipping nine languages with them. The canonical also
 * pointed at a path with no locale segment, which only exists as a 307 to a
 * negotiated locale, and a canonical must name an indexable page rather than a
 * redirect. Replacing `alternates` also discarded the hreflang map and
 * `x-default` the layout supplies, so those pages advertised no translations at
 * all while the sitemap insisted they had eight.
 *
 * Every page therefore builds the whole block, not just its canonical.
 */
export function localizedAlternates(
  locale: Locale,
  path = "",
): { canonical: string; languages: Record<string, string> } {
  const clean = path === "/" ? "" : path;
  return {
    canonical: absoluteUrl(`/${locale}${clean}`),
    languages: {
      ...Object.fromEntries(
        locales.map((l) => [localeHreflang[l], absoluteUrl(`/${l}${clean}`)]),
      ),
      // Where a reader's language matches none of the above. Points at the
      // default locale, which is also where a locale-less path lands.
      "x-default": absoluteUrl(`/${routing.defaultLocale}${clean}`),
    },
  };
}
