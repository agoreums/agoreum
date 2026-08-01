"use client";

import { useTranslations } from "next-intl";

import { truncateAddress } from "@/components/auth/connect-wallet";
import { useAuth } from "@/components/auth/auth-provider";

/**
 * The account overview.
 *
 * Identity on Agoreum is anchored to a wallet, not an editable profile, so this
 * screen reads the real account and does not offer fields the platform has no
 * endpoint to save. What can be changed, appearance, notifications, wallets, has
 * its own screen.
 */
export function ProfileView() {
  const t = useTranslations("settingsProfile");
  const { status, user } = useAuth();

  if (status !== "authenticated" || !user) {
    return (
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
        <p className="text-[var(--text-secondary)]">{t("signInRequired")}</p>
      </div>
    );
  }

  const rows: { label: string; value: string; mono?: boolean }[] = [
    {
      label: t("name"),
      value: user.display_name || user.username || t("unnamed"),
    },
    { label: t("address"), value: user.primary_address, mono: true },
    { label: t("email"), value: user.email ?? t("noEmail") },
    { label: t("role"), value: t(`roles.${user.role}`) },
    {
      label: t("memberSince"),
      value: new Date(user.created_at).toLocaleDateString(),
    },
  ];

  return (
    <dl className="divide-y divide-[var(--border-subtle)] rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
      {rows.map((row) => (
        <div
          key={row.label}
          className="flex flex-col gap-1 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"
        >
          <dt className="text-sm text-[var(--text-muted)]">{row.label}</dt>
          <dd
            className={`text-sm text-[var(--text-primary)] ${
              row.mono ? "break-all font-mono" : ""
            }`}
          >
            {row.mono ? (
              <span className="hidden sm:inline">{row.value}</span>
            ) : (
              row.value
            )}
            {row.mono ? (
              <span className="sm:hidden">{truncateAddress(row.value)}</span>
            ) : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}
