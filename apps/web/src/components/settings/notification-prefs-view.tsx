"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import {
  ApiError,
  notificationsApi,
  type EmailStatus,
  type NotificationCategory,
  type NotificationChannel,
  type NotificationPreference,
} from "@/lib/api";

const CATEGORIES: NotificationCategory[] = [
  "order",
  "payment",
  "message",
  "reputation",
  "security",
  "system",
];
const CHANNELS: NotificationChannel[] = ["in_app", "email"];

/** A category+channel is enabled unless a stored preference says otherwise. */
function key(category: string, channel: string) {
  return `${category}:${channel}`;
}

/**
 * Delivery preferences: for each kind of event, which channels reach you.
 *
 * Anything not explicitly turned off is on, matching the API's default. Security
 * notices cannot be turned off, and the control reflects that rather than letting
 * a toggle fail silently. When this deployment cannot send email, a banner says so
 * plainly so a disabled email channel is never mistaken for a preference.
 */
export function NotificationPrefsView() {
  const t = useTranslations("settingsNotifications");
  const { status, accessToken } = useAuth();

  const [enabled, setEnabled] = useState<Record<string, boolean> | null>(null);
  const [email, setEmail] = useState<EmailStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) return;
    let cancelled = false;
    async function run() {
      try {
        const [prefs, mail] = await Promise.all([
          notificationsApi.preferences(accessToken!),
          notificationsApi.emailStatus().catch(() => null),
        ]);
        if (cancelled) return;
        const map: Record<string, boolean> = {};
        for (const c of CATEGORIES)
          for (const ch of CHANNELS) map[key(c, ch)] = true;
        for (const p of prefs) map[key(p.category, p.channel)] = p.enabled;
        setEnabled(map);
        setEmail(mail);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t("loadFailed"));
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [status, accessToken, t]);

  async function toggle(
    category: NotificationCategory,
    channel: NotificationChannel,
  ) {
    if (!accessToken || !enabled || category === "security") return;
    const k = key(category, channel);
    const next = !enabled[k];
    setEnabled({ ...enabled, [k]: next });
    setPending(k);
    try {
      const saved: NotificationPreference = { category, channel, enabled: next };
      await notificationsApi.setPreference(accessToken, saved);
    } catch (err) {
      // Revert on failure so the control never lies about what is stored.
      setEnabled((prev) => (prev ? { ...prev, [k]: !next } : prev));
      setError(err instanceof ApiError ? err.message : t("saveFailed"));
    } finally {
      setPending(null);
    }
  }

  if (status !== "authenticated") {
    return (
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
        <p className="text-[var(--text-secondary)]">{t("signInRequired")}</p>
      </div>
    );
  }

  if (enabled === null && !error) {
    return (
      <div className="h-48 animate-pulse rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)]" />
    );
  }

  return (
    <div className="space-y-5">
      {error ? (
        <p className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-4 text-sm text-danger-500">
          {error}
        </p>
      ) : null}

      {email && !email.enabled ? (
        <p className="rounded-[var(--radius-card)] border border-warning-500/40 bg-warning-500/5 p-4 text-sm text-[var(--text-secondary)]">
          {t("emailDisabled")}
        </p>
      ) : null}

      <div className="overflow-x-auto rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
        <table className="w-full min-w-[24rem] text-sm">
          <thead>
            <tr className="border-b border-[var(--border-subtle)] text-xs uppercase tracking-wider text-[var(--text-muted)]">
              <th className="px-5 py-3 text-start font-medium">{t("category")}</th>
              {CHANNELS.map((ch) => (
                <th key={ch} className="px-5 py-3 text-center font-medium">
                  {t(`channels.${ch}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border-subtle)]">
            {CATEGORIES.map((category) => {
              const locked = category === "security";
              return (
                <tr key={category}>
                  <td className="px-5 py-3">
                    <span className="font-medium text-[var(--text-primary)]">
                      {t(`categories.${category}`)}
                    </span>
                    {locked ? (
                      <span className="mt-0.5 block text-xs text-[var(--text-muted)]">
                        {t("securityLocked")}
                      </span>
                    ) : null}
                  </td>
                  {CHANNELS.map((channel) => {
                    const k = key(category, channel);
                    const on = enabled?.[k] ?? true;
                    return (
                      <td key={channel} className="px-5 py-3 text-center">
                        <button
                          type="button"
                          role="switch"
                          aria-checked={on}
                          aria-label={`${t(`categories.${category}`)} · ${t(`channels.${channel}`)}`}
                          disabled={locked || pending === k}
                          onClick={() => toggle(category, channel)}
                          className={`inline-flex h-6 w-11 items-center rounded-full border transition-colors ${
                            on
                              ? "justify-end border-brand-500 bg-brand-500/80"
                              : "justify-start border-[var(--border-strong)] bg-[var(--surface-raised)]"
                          } ${locked ? "opacity-60" : ""}`}
                        >
                          <span className="mx-0.5 size-5 rounded-full bg-white shadow" />
                        </button>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
