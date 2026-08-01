import type { IconKey } from "@/components/app/icons";

/**
 * The application's navigation, grouped into sections. Every entry resolves to a
 * real, built page, so the shell never advertises a destination that 404s. New
 * feature screens are added here as they land.
 */
export type AppNavItem = {
  /** Translation key under the `app.nav` namespace. */
  key: string;
  href: string;
  icon: IconKey;
};

export type AppNavSection = {
  /** Translation key under `app.nav.sections`, or null for the top group. */
  key: string | null;
  items: AppNavItem[];
};

export const appNav: AppNavSection[] = [
  {
    key: null,
    items: [{ key: "dashboard", href: "/dashboard", icon: "dashboard" }],
  },
  {
    key: "settings",
    items: [
      {
        key: "organizations",
        href: "/settings/organizations",
        icon: "organizations",
      },
      { key: "apiKeys", href: "/settings/api-keys", icon: "key" },
      { key: "webhooks", href: "/settings/webhooks", icon: "webhook" },
    ],
  },
];
