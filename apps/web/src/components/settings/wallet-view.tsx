"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { ApiError, authApi, type WalletSummary } from "@/lib/api";

/**
 * Wallets linked to the account.
 *
 * Wallets are proven, not entered: a wallet becomes verified by signing in with
 * it, and payouts only ever go to a verified one. This screen shows that real
 * state; it does not offer to "add" a wallet by typing an address, because control
 * is proven by signature, never asserted.
 */
export function WalletView() {
  const t = useTranslations("settingsWallet");
  const { status, accessToken } = useAuth();

  const [wallets, setWallets] = useState<WalletSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) return;
    let cancelled = false;
    async function run() {
      try {
        const list = await authApi.wallets(accessToken!);
        if (!cancelled) {
          setWallets(list);
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

  if (status !== "authenticated") {
    return (
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
        <p className="text-[var(--text-secondary)]">{t("signInRequired")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {error ? (
        <p className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-4 text-sm text-danger-500">
          {error}
        </p>
      ) : null}

      <p className="text-sm text-[var(--text-secondary)]">{t("hint")}</p>

      {wallets === null ? (
        <div className="space-y-3" aria-hidden="true">
          {[0, 1].map((i) => (
            <div
              key={i}
              className="h-16 animate-pulse rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)]"
            />
          ))}
        </div>
      ) : wallets.length === 0 ? (
        <p className="rounded-[var(--radius-card)] border border-dashed border-[var(--border-subtle)] p-8 text-center text-sm text-[var(--text-muted)]">
          {t("empty")}
        </p>
      ) : (
        <ul className="divide-y divide-[var(--border-subtle)] rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
          {wallets.map((w) => (
            <li
              key={w.id}
              className="flex flex-wrap items-center justify-between gap-3 px-5 py-4"
            >
              <div className="min-w-0">
                <p className="break-all font-mono text-sm text-[var(--text-primary)]">
                  {w.address}
                </p>
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  {t("chain", { id: w.chain_id })} · {w.provider}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {w.is_payout ? (
                  <span className="rounded-full border border-brand-500/40 px-2 py-0.5 text-xs text-brand-500">
                    {t("payout")}
                  </span>
                ) : null}
                <span
                  className={`rounded-full border px-2 py-0.5 text-xs ${
                    w.verification_status === "verified"
                      ? "border-success-500/40 text-success-500"
                      : "border-[var(--border-subtle)] text-[var(--text-muted)]"
                  }`}
                >
                  {w.verification_status === "verified"
                    ? t("verified")
                    : t("unverified")}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
