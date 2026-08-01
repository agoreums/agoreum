"use client";

import { useTranslations } from "next-intl";

import { LocaleSwitcher } from "@/components/layout/locale-switcher";
import { ThemeToggle } from "@/components/layout/theme-toggle";

/**
 * Appearance and language.
 *
 * Both are genuine client preferences the app already honours: the theme is
 * persisted and applied before first paint, and the language switch rewrites the
 * route to the chosen locale. This screen just gives them a settled home with room
 * to breathe, reusing the exact controls the header uses so behaviour cannot drift.
 */
export function AppearanceView() {
  const t = useTranslations("settingsAppearance");

  return (
    <div className="divide-y divide-[var(--border-subtle)] rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
      <div className="flex flex-col gap-3 px-5 py-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium text-[var(--text-primary)]">
            {t("theme")}
          </p>
          <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
            {t("themeHint")}
          </p>
        </div>
        <ThemeToggle />
      </div>

      <div className="flex flex-col gap-3 px-5 py-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium text-[var(--text-primary)]">
            {t("language")}
          </p>
          <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
            {t("languageHint")}
          </p>
        </div>
        <LocaleSwitcher />
      </div>
    </div>
  );
}
