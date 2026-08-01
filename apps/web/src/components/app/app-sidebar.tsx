"use client";

import { useTranslations } from "next-intl";

import { Icon } from "@/components/app/icons";
import { appNav } from "@/components/app/nav";
import { LogoWordmark } from "@/components/brand/logo";
import { Link, usePathname } from "@/i18n/navigation";

/**
 * The navigation rail. Shared verbatim by the permanent desktop sidebar and the
 * mobile/tablet drawer, so the two can never drift. `onNavigate` lets the drawer
 * close itself the moment a destination is chosen.
 */
export function AppSidebar({ onNavigate }: { onNavigate?: () => void }) {
  const t = useTranslations("app.nav");
  const pathname = usePathname();

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto px-4 py-5">
      <Link
        href="/dashboard"
        onClick={onNavigate}
        className="rounded-lg px-1 transition-opacity hover:opacity-85"
        aria-label={t("home")}
      >
        <LogoWordmark />
      </Link>

      <nav className="flex flex-1 flex-col gap-6" aria-label={t("primary")}>
        {appNav.map((section, i) => (
          <div key={section.key ?? `section-${i}`} className="flex flex-col gap-1">
            {section.key ? (
              <p className="px-3 pb-1 text-[0.6875rem] font-medium uppercase tracking-wider text-[var(--text-muted)]">
                {t(`sections.${section.key}`)}
              </p>
            ) : null}
            {section.items.map((item) => {
              const active =
                pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors ${
                    active
                      ? "bg-brand-500/10 text-[var(--text-primary)]"
                      : "text-[var(--text-secondary)] hover:bg-[var(--surface-raised)] hover:text-[var(--text-primary)]"
                  }`}
                >
                  <Icon
                    name={item.icon}
                    className={active ? "text-brand-500" : "text-[var(--text-muted)]"}
                  />
                  {t(`items.${item.key}`)}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <Link
        href="/"
        onClick={onNavigate}
        className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text-primary)]"
      >
        <Icon name="external" className="text-[var(--text-muted)]" />
        {t("backToSite")}
      </Link>
    </div>
  );
}
