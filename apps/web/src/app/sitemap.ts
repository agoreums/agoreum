import type { MetadataRoute } from "next";

import { localeHreflang, locales } from "@/i18n/routing";
import { absoluteUrl, apiBaseUrl } from "@/lib/site";

// Re-generated hourly so newly published agents and services are discoverable
// without a full redeploy.
export const revalidate = 3600;

type Route = {
  path: string;
  priority: number;
  changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"];
};

// Public, indexable pages. Authenticated and personal surfaces (dashboard,
// settings, subscriptions) are deliberately excluded, matching robots.ts.
const staticRoutes: Route[] = [
  { path: "/", priority: 1, changeFrequency: "weekly" },
  { path: "/marketplace", priority: 0.9, changeFrequency: "daily" },
  { path: "/agents", priority: 0.8, changeFrequency: "daily" },
  { path: "/agents/register", priority: 0.6, changeFrequency: "monthly" },
  { path: "/docs", priority: 0.7, changeFrequency: "weekly" },
  { path: "/docs/api", priority: 0.7, changeFrequency: "weekly" },
  { path: "/docs/sdks", priority: 0.7, changeFrequency: "weekly" },
  { path: "/contact", priority: 0.4, changeFrequency: "yearly" },
  { path: "/security", priority: 0.4, changeFrequency: "monthly" },
  // Higher than the other trust pages on purpose. Anyone handed a receipt
  // needs to find this without being told where it is, and somebody
  // deciding whether to believe the reputation claim should land on the
  // page that lets them check it rather than on one that describes it.
  { path: "/verify", priority: 0.7, changeFrequency: "monthly" },
  { path: "/support", priority: 0.4, changeFrequency: "monthly" },
  { path: "/terms", priority: 0.3, changeFrequency: "yearly" },
  { path: "/privacy", priority: 0.3, changeFrequency: "yearly" },
];

function localizedUrl(locale: string, path: string): string {
  const suffix = path === "/" ? "" : path;
  return absoluteUrl(`/${locale}${suffix}`);
}

function entry(route: Route, lastModified: Date): MetadataRoute.Sitemap {
  return locales.map((locale) => ({
    url: localizedUrl(locale, route.path),
    lastModified,
    changeFrequency: route.changeFrequency,
    priority: route.priority,
    alternates: {
      languages: Object.fromEntries(
        locales.map((l) => [localeHreflang[l], localizedUrl(l, route.path)]),
      ),
    },
  }));
}

// Best-effort discovery of dynamic pages. A failure here never breaks the
// sitemap; the static routes always ship.
async function dynamicRoutes(): Promise<Route[]> {
  const routes: Route[] = [];
  const controller = AbortSignal.timeout(4000);
  try {
    const [agentsRes, servicesRes] = await Promise.all([
      fetch(`${apiBaseUrl}/api/v1/marketplace/agents?limit=60&sort=newest`, {
        signal: controller,
        next: { revalidate: 3600 },
      }),
      fetch(`${apiBaseUrl}/api/v1/marketplace/services?limit=60&sort=newest`, {
        signal: controller,
        next: { revalidate: 3600 },
      }),
    ]);

    if (agentsRes.ok) {
      const data = (await agentsRes.json()) as { items?: { slug?: string }[] };
      for (const a of data.items ?? []) {
        if (a.slug) {
          routes.push({ path: `/agents/${a.slug}`, priority: 0.7, changeFrequency: "weekly" });
        }
      }
    }
    if (servicesRes.ok) {
      const data = (await servicesRes.json()) as {
        items?: { slug?: string; agent?: { slug?: string } }[];
      };
      for (const s of data.items ?? []) {
        if (s.slug && s.agent?.slug) {
          routes.push({
            path: `/agents/${s.agent.slug}/services/${s.slug}`,
            priority: 0.6,
            changeFrequency: "weekly",
          });
        }
      }
    }
  } catch {
    // Network error or timeout: return whatever was collected so far.
  }
  return routes;
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const lastModified = new Date();
  const dynamic = await dynamicRoutes();
  return [...staticRoutes, ...dynamic].flatMap((route) => entry(route, lastModified));
}
