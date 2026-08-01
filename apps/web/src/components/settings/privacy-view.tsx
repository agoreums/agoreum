"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { Link } from "@/i18n/navigation";
import { ApiError, authApi } from "@/lib/api";

/**
 * Privacy and account controls.
 *
 * The platform holds little: a wallet address that is the identity, an optional
 * email used only for notifications, and the record of real activity. This screen
 * states that plainly and offers the two controls that genuinely exist, removing
 * the email (managed on the profile) and pausing the account. Pausing signs the
 * account out everywhere and it stays paused until the owner signs in again.
 */
export function PrivacyView() {
  const t = useTranslations("settingsPrivacy");
  const { status, user, accessToken, signOut } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status !== "authenticated" || !user) {
    return (
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
        <p className="text-[var(--text-secondary)]">{t("signInRequired")}</p>
      </div>
    );
  }

  async function pause() {
    if (!accessToken) return;
    if (!window.confirm(t("pauseConfirm"))) return;
    setBusy(true);
    setError(null);
    try {
      await authApi.suspend(accessToken);
      // The server has revoked every session; end the local one and return to the
      // sign-in gate.
      await signOut();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("pauseFailed"));
      setBusy(false);
    }
  }

  const held = [t("dataAddress"), t("dataEmail"), t("dataActivity")];

  return (
    <div className="max-w-2xl space-y-8">
      <section className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-5">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          {t("dataTitle")}
        </h2>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">{t("dataHint")}</p>
        <ul className="mt-3 space-y-2">
          {held.map((item) => (
            <li
              key={item}
              className="flex gap-2 text-sm text-[var(--text-secondary)]"
            >
              <span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-brand-500" />
              {item}
            </li>
          ))}
        </ul>
        <p className="mt-4 text-sm text-[var(--text-secondary)]">
          {t("emailManaged")}{" "}
          <Link href="/settings/profile" className="text-brand-500 hover:underline">
            {t("emailManagedLink")}
          </Link>
          .
        </p>
      </section>

      <section className="rounded-[var(--radius-card)] border border-danger-500/30 p-5">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          {t("pauseTitle")}
        </h2>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">{t("pauseHint")}</p>
        {error ? <p className="mt-3 text-sm text-danger-500">{error}</p> : null}
        <button
          type="button"
          onClick={pause}
          disabled={busy}
          className="mt-4 inline-flex rounded-xl border border-danger-500/50 px-5 py-2.5 text-sm font-medium text-danger-500 transition-colors hover:bg-danger-500/5 disabled:opacity-60"
        >
          {busy ? t("pausing") : t("pause")}
        </button>
      </section>
    </div>
  );
}
