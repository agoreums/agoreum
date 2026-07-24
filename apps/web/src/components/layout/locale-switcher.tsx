"use client";

import { useLocale, useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { useTransition } from "react";

import { usePathname, useRouter } from "@/i18n/navigation";
import { localeNames, locales, type Locale } from "@/i18n/routing";

/**
 * Language selector.
 *
 * Implemented as a native `<select>` on purpose: it is keyboard accessible, works
 * without custom focus management for screen readers, and gets the platform's own
 * picker on mobile. A bespoke dropdown here would be worse in every way that counts.
 */
export function LocaleSwitcher() {
  const t = useTranslations("nav");
  const locale = useLocale() as Locale;
  const router = useRouter();
  const pathname = usePathname();
  const params = useParams();
  const [isPending, startTransition] = useTransition();

  function onChange(nextLocale: string) {
    startTransition(() => {
      // `params` is forwarded so dynamic segments (e.g. /agents/[id]) survive the
      // locale change instead of collapsing back to the section root.
      router.replace(
        // @ts-expect-error -- pathname is a valid route; params are supplied dynamically
        { pathname, params },
        { locale: nextLocale as Locale },
      );
    });
  }

  return (
    <label className="relative inline-flex items-center">
      <span className="sr-only">{t("selectLanguage")}</span>
      <select
        value={locale}
        disabled={isPending}
        onChange={(e) => onChange(e.target.value)}
        className="cursor-pointer appearance-none rounded-lg border border-[var(--border-subtle)] bg-transparent py-1.5 ps-3 pe-8 text-sm text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)] disabled:opacity-60"
      >
        {locales.map((l) => (
          <option key={l} value={l} className="bg-ink-900 text-ink-50">
            {localeNames[l]}
          </option>
        ))}
      </select>
      <svg
        aria-hidden="true"
        viewBox="0 0 20 20"
        className="pointer-events-none absolute end-2.5 h-3.5 w-3.5 text-[var(--text-muted)]"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
      >
        <path d="m5 7.5 5 5 5-5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </label>
  );
}
