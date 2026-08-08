"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Link } from "@/i18n/navigation";
import { ApiError, authApi } from "@/lib/api";

type State = "missing" | "working" | "confirmed" | "failed";

// Matches the primary Button, which renders a <button> and so cannot wrap a link.
const LINK_BUTTON =
  "inline-flex items-center justify-center gap-2 rounded-xl bg-brand-600 px-5 py-2.5 " +
  "text-sm font-medium text-white transition-colors hover:bg-brand-500";

/**
 * Spends the token from the confirmation link.
 *
 * Runs on mount rather than behind a button. The person already expressed intent
 * by opening the link; asking them to click a second time to do the thing they
 * just asked for is friction with no security value, since possession of the
 * token is the whole proof either way.
 *
 * The token is read from the query string directly and never rendered, logged,
 * or put into a link. It is single use, so it is spent by the time this resolves,
 * but a token sitting visibly on screen is a token that ends up in a screenshot.
 */
export function VerifyEmailView() {
  const t = useTranslations("verifyEmail");
  // Read during render rather than in the effect, so the "no token" case is
  // derived state rather than a setState the effect fires on mount.
  const token = useSearchParams().get("token");
  const [state, setState] = useState<State>(token ? "working" : "missing");
  const [detail, setDetail] = useState<string | null>(null);
  // React runs effects twice in development. Without this the second run spends
  // an already-spent token and reports failure for a confirmation that worked.
  const attempted = useRef(false);

  useEffect(() => {
    if (attempted.current) return;
    attempted.current = true;

    if (!token) return;

    authApi
      .confirmEmail(token)
      .then(() => setState("confirmed"))
      .catch((err) => {
        setDetail(err instanceof ApiError ? err.message : null);
        setState("failed");
      });
  }, [token]);

  if (state === "working") {
    return <p className="text-[var(--text-secondary)]">{t("working")}</p>;
  }

  if (state === "confirmed") {
    return (
      <div className="space-y-4">
        <p className="text-[var(--text-primary)]">{t("confirmed")}</p>
        <p className="text-sm text-[var(--text-secondary)]">{t("confirmedHint")}</p>
        <Link href="/settings/profile" className={LINK_BUTTON}>
          {t("toProfile")}
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-[var(--text-primary)]">
        {state === "missing" ? t("missing") : t("failed")}
      </p>
      {/* The API's own wording, which distinguishes expired from already used
          from issued for a different address. Repeating it here beats a generic
          message that leaves somebody guessing which of those happened. */}
      {detail ? (
        <p className="text-sm text-[var(--text-secondary)]">{detail}</p>
      ) : null}
      <p className="text-sm text-[var(--text-secondary)]">{t("failedHint")}</p>
      <Link href="/settings/profile" className={LINK_BUTTON}>
        {t("toProfile")}
      </Link>
    </div>
  );
}
