import { getTranslations } from "next-intl/server";

import { LogoWordmark } from "@/components/brand/logo";
import { ConnectWalletButton } from "@/components/auth/connect-wallet";
import { LocaleSwitcher } from "@/components/layout/locale-switcher";
import { MobileNav } from "@/components/layout/mobile-nav";
import { Link } from "@/i18n/navigation";

/** Primary navigation. Kept in one place so header and mobile drawer cannot diverge. */
export const primaryNav = [
  { key: "marketplace", href: "/marketplace" },
  { key: "agents", href: "/agents" },
  { key: "services", href: "/services" },
  { key: "docs", href: "/docs" },
] as const;

export async function SiteHeader() {
  const t = await getTranslations("nav");

  const items = primaryNav.map((item) => ({
    href: item.href,
    label: t(item.key),
  }));

  return (
    <header className="sticky top-0 z-50 border-b border-[var(--border-subtle)] bg-[color-mix(in_oklab,var(--surface-base)_82%,transparent)] backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="rounded-lg transition-opacity hover:opacity-85"
        >
          <LogoWordmark priority />
        </Link>

        <nav
          aria-label="Primary"
          className="hidden items-center gap-1 md:flex"
        >
          {items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-lg px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text-primary)]"
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <div className="hidden sm:block">
            <LocaleSwitcher />
          </div>
          <ConnectWalletButton />
          <MobileNav items={items} menuLabel={t("openMenu")} closeLabel={t("closeMenu")} />
        </div>
      </div>
    </header>
  );
}
