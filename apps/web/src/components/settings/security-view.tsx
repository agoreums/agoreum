"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Button, Skeleton } from "@/components/app/ui";
import { truncateAddress } from "@/components/auth/connect-wallet";
import { useAuth } from "@/components/auth/auth-provider";
import { ApiError, authApi, type SessionSummary } from "@/lib/api";

/**
 * Security: the sessions currently able to act as this account, and a single
 * control to end all of them. Signing out everywhere revokes every refresh token
 * server-side, so a device that was signed in can no longer refresh its access.
 */
export function SecurityView() {
  const t = useTranslations("settingsSecurity");
  const { status, accessToken, signOut } = useAuth();

  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) return;
    let cancelled = false;
    async function run() {
      try {
        const list = await authApi.sessions(accessToken!);
        if (!cancelled) {
          setSessions(list);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t("loadFailed"));
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [status, accessToken, t]);

  async function signOutEverywhere() {
    if (!window.confirm(t("signOutAllConfirm"))) return;
    setBusy(true);
    try {
      await signOut(true);
    } finally {
      setBusy(false);
    }
  }

  if (status !== "authenticated") {
    return (
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
        <p className="text-[var(--text-secondary)]">{t("signInRequired")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error ? (
        <p className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-4 text-sm text-danger-500">
          {error}
        </p>
      ) : null}

      <section>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
            {t("sessionsTitle")}
          </h2>
          <Button variant="danger" onClick={signOutEverywhere} disabled={busy}>
            {busy ? t("signingOut") : t("signOutAll")}
          </Button>
        </div>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">{t("sessionsHint")}</p>

        {sessions === null ? (
          <div className="mt-4 space-y-3">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-16" />
            ))}
          </div>
        ) : sessions.length === 0 ? (
          <p className="mt-4 rounded-[var(--radius-card)] border border-dashed border-[var(--border-subtle)] p-8 text-center text-sm text-[var(--text-muted)]">
            {t("noSessions")}
          </p>
        ) : (
          <ul className="mt-4 divide-y divide-[var(--border-subtle)] rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
            {sessions.map((s) => (
              <li key={s.id} className="px-5 py-4">
                <p dir="ltr" className="font-mono text-sm text-[var(--text-primary)]">
                  {truncateAddress(s.address)}
                </p>
                {s.user_agent ? (
                  <p className="mt-1 truncate text-xs text-[var(--text-secondary)]">
                    {s.user_agent}
                  </p>
                ) : null}
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  {t("lastUsed", { when: new Date(s.last_used_at).toLocaleString() })}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
