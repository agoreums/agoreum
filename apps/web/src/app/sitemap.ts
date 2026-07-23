import type { MetadataRoute } from "next";

import { defaultLocale, localeHreflang, locales } from "@/i18n/routing";
import { absoluteUrl } from "@/lib/site";

export const dynamic = "force-static";

/**
 * Static routes that exist today.
 *
 * Dynamic entries — agent profiles, service pages, category listings — are added
 * in the stage that makes those routes real. Listing URLs that 404 would actively
 * harm indexing, so this file only ever contains pages that actually render.
 */
const staticRoutes: { path: string; priority: number; changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"] }[] = [
  { path: "/", priority: 1, changeFrequency: "weekly" },
];

function localizedUrl(locale: string, path: string): string {
  const prefix = locale === defaultLocale ? "" : `/${locale}`;
  const suffix = path === "/" ? "" : path;
  return absoluteUrl(`${prefix}${suffix}` || "/");
}

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();

  return staticRoutes.flatMap((route) =>
    locales.map((locale) => ({
      url: localizedUrl(locale, route.path),
      lastModified,
      changeFrequency: route.changeFrequency,
      priority: route.priority,
      alternates: {
        languages: Object.fromEntries(
          locales.map((l) => [localeHreflang[l], localizedUrl(l, route.path)]),
        ),
      },
    })),
  );
}
