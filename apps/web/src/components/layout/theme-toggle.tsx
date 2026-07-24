"use client";

import { useTranslations } from "next-intl";
import type { ReactElement } from "react";

import { useStored, writeStored } from "@/lib/use-stored-state";

type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "agoreum-theme";
const ORDER: readonly Theme[] = ["light", "dark", "system"];

function isTheme(value: string): value is Theme {
  return (ORDER as readonly string[]).includes(value);
}

/** Persist the choice and reflect it on the document (the pre-paint script reads it on load). */
function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  writeStored(STORAGE_KEY, theme);
}

function SunIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" />
    </svg>
  );
}

function SystemIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </svg>
  );
}

const ICONS: Record<Theme, () => ReactElement> = {
  light: SunIcon,
  dark: MoonIcon,
  system: SystemIcon,
};

/**
 * Light / dark / system theme control.
 *
 * A three-state segmented control rather than a single cycling button: the
 * current choice is always visible, which a blind toggle hides. Icons carry the
 * meaning (sun, moon, monitor) with a screen-reader label on each; no text
 * labels crowd the header. The current theme is read from the store, so there is
 * no effect and no post-mount state flip.
 */
export function ThemeToggle() {
  const t = useTranslations("theme");
  const stored = useStored(STORAGE_KEY, "system");
  const theme: Theme = isTheme(stored) ? stored : "system";

  return (
    <div
      role="radiogroup"
      aria-label={t("label")}
      className="inline-flex items-center gap-0.5 rounded-lg border border-[var(--border-subtle)] p-0.5"
    >
      {ORDER.map((option) => {
        const Icon = ICONS[option];
        const active = theme === option;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={t(option)}
            title={t(option)}
            onClick={() => apply(option)}
            className={`inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors ${
              active
                ? "bg-[var(--surface-overlay)] text-[var(--text-primary)]"
                : "text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            }`}
          >
            <Icon />
          </button>
        );
      })}
    </div>
  );
}
