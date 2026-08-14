// @vitest-environment node
/**
 * Canonical URLs and hreflang, per locale.
 *
 * Nine locales are only worth shipping if a search engine indexes nine pages.
 * Every page except the locale root declared the same canonical URL for all
 * nine, which says they are duplicates of one page, so eight would be dropped.
 * That canonical also had no locale segment, and such a path exists only as a
 * redirect, which a canonical must never point at.
 *
 * Both were invisible in the source: the pages looked like they set a sensible
 * canonical, and only the rendered HTML showed all nine agreeing.
 *
 * Next merges page metadata over layout metadata field by field, so a page that
 * sets `alternates` replaces the layout's whole block, including the hreflang
 * map and x-default. That is why pages must build the entire block rather than
 * just a canonical, and why this asserts the block rather than one field.
 */
import { describe, expect, it } from "vitest";

import { localeHreflang, locales, routing } from "@/i18n/routing";
import { localizedAlternates } from "@/lib/site";

const PATHS = ["", "/marketplace", "/agents", "/docs", "/terms"];

describe("localizedAlternates", () => {
  it("gives every locale its own canonical", () => {
    for (const path of PATHS) {
      const seen = locales.map(
        (l) => localizedAlternates(l, path).canonical,
      );
      expect(new Set(seen).size, `all locales share one canonical for ${path || "/"}`).toBe(
        locales.length,
      );
    }
  });

  it("points each canonical at its own locale, not a redirect", () => {
    for (const locale of locales) {
      for (const path of PATHS) {
        const { canonical } = localizedAlternates(locale, path);
        expect(canonical).toBe(`https://agoreum.xyz/${locale}${path}`);
        // A path with no locale segment is a 307 to a negotiated one. A
        // canonical naming a redirect is the defect this replaced.
        expect(canonical).toMatch(new RegExp(`/${locale}(/|$)`));
      }
    }
  });

  it("advertises every locale, in the hreflang code each one uses", () => {
    const { languages } = localizedAlternates("en", "/docs");
    for (const locale of locales) {
      const code = localeHreflang[locale];
      expect(languages[code], `${locale} missing from hreflang`).toBe(
        `https://agoreum.xyz/${locale}/docs`,
      );
    }
  });

  it("names a fallback for readers whose language matches none of ours", () => {
    for (const path of PATHS) {
      const { languages } = localizedAlternates("ar", path);
      expect(languages["x-default"]).toBe(
        `https://agoreum.xyz/${routing.defaultLocale}${path}`,
      );
    }
  });

  it("keeps the alternates identical whichever locale renders the page", () => {
    // The hreflang map describes the whole set, so it cannot depend on who is
    // asking. Only the canonical moves.
    const fromEnglish = localizedAlternates("en", "/marketplace").languages;
    const fromArabic = localizedAlternates("ar", "/marketplace").languages;
    expect(fromArabic).toEqual(fromEnglish);
  });

  it("treats the locale root as the locale itself, with no trailing slash", () => {
    expect(localizedAlternates("ja", "").canonical).toBe("https://agoreum.xyz/ja");
    expect(localizedAlternates("ja", "/").canonical).toBe("https://agoreum.xyz/ja");
  });
});
