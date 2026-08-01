"use client";

import { useTranslations } from "next-intl";

import { Link, usePathname } from "@/i18n/navigation";

/**
 * The settings section tab bar. Horizontal and scrollable so it sits cleanly
 * beneath the page title without competing with the global sidebar for a second
 * left rail. Every entry resolves to a real settings screen.
 */
const items = [
  { key: "profile", href: "/settings/profile" },
  { key: "security", href: "/settings/security" },
  { key: "wallet", href: "/settings/wallet" },
  { key: "notifications", href: "/settings/notifications" },
  { key: "appearance", href: "/settings/appearance" },
  { key: "organizations", href: "/settings/organizations" },
  { key: "apiKeys", href: "/settings/api-keys" },
  { key: "webhooks", href: "/settings/webhooks" },
];

export function SettingsNav() {
  const t = useTranslations("settings.nav");
  const pathname = usePathname();

  return (
    <nav
      aria-label={t("label")}
      className="-mx-1 overflow-x-auto border-b border-[var(--border-subtle)]"
    >
      <ul className="flex min-w-max gap-1 px-1">
        {items.map((item) => {
          const active =
            pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`-mb-px inline-block whitespace-nowrap border-b-2 px-3 py-2.5 text-sm transition-colors ${
                  active
                    ? "border-brand-500 text-[var(--text-primary)]"
                    : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                }`}
              >
                {t(`items.${item.key}`)}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
