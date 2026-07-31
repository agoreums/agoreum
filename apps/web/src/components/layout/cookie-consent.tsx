"use client";

import { useTranslations } from "next-intl";
import { useEffect } from "react";

import { Link } from "@/i18n/navigation";
import { useStored, writeStored } from "@/lib/use-stored-state";

const STORAGE_KEY = "agoreum-analytics-consent";
const UMAMI_URL = process.env.NEXT_PUBLIC_UMAMI_URL;
const UMAMI_WEBSITE_ID = process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID;

/** Injects the Umami tracker once, only after consent. */
function loadAnalytics() {
  if (!UMAMI_URL || !UMAMI_WEBSITE_ID) return;
  if (document.getElementById("umami-analytics")) return;
  const s = document.createElement("script");
  s.id = "umami-analytics";
  s.defer = true;
  s.src = `${UMAMI_URL}/script.js`;
  s.setAttribute("data-website-id", UMAMI_WEBSITE_ID);
  // Keep collection under /insights so it stays same-origin.
  s.setAttribute("data-host-url", UMAMI_URL);
  document.head.appendChild(s);
}

/**
 * Analytics consent.
 *
 * Umami is cookieless and stores no personal data, but a clear disclosure and an
 * explicit choice are shown anyway, nobody is tracked silently. Analytics load
 * only after "Accept"; "Decline" is remembered and nothing is sent. The decision
 * is read from the store (localStorage), so there is no state held here and no
 * `setState` in an effect. The lone effect performs a side effect, injecting the
 * tracker for a visitor who accepted on a previous visit, which is exactly what
 * an effect is for.
 */
export function CookieConsent() {
  const t = useTranslations("consent");
  const decision = useStored(STORAGE_KEY, "");

  useEffect(() => {
    if (decision === "accepted") loadAnalytics();
  }, [decision]);

  function choose(next: "accepted" | "declined") {
    writeStored(STORAGE_KEY, next);
    if (next === "accepted") loadAnalytics();
  }

  if (decision === "accepted" || decision === "declined") return null;

  return (
    <div
      role="dialog"
      aria-label={t("title")}
      className="fixed inset-x-0 bottom-0 z-50 px-4 pb-4 sm:px-6"
    >
      <div className="mx-auto flex max-w-3xl flex-col gap-4 rounded-[var(--radius-card)] border border-[var(--border-strong)] bg-[var(--surface-overlay)] p-5 shadow-[var(--shadow-lifted)] sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
          {t("body")}{" "}
          <Link
            href="/privacy"
            className="text-[var(--text-primary)] underline decoration-[var(--border-strong)] underline-offset-4 hover:decoration-current"
          >
            {t("privacyLink")}
          </Link>
        </p>
        <div className="flex flex-none gap-2">
          <button
            type="button"
            onClick={() => choose("declined")}
            className="rounded-lg border border-[var(--border-subtle)] px-4 py-2 text-sm text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]"
          >
            {t("decline")}
          </button>
          <button
            type="button"
            onClick={() => choose("accepted")}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-500"
          >
            {t("accept")}
          </button>
        </div>
      </div>
    </div>
  );
}
