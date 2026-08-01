"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import {
  ApiError,
  subscriptionsApi,
  type SubscriptionPayment,
  type SubscriptionStatus,
} from "@/lib/api";

/**
 * Payments: the subscriptions this account holds and the on-chain payments that
 * funded them. Everything shown is settled record read from the chain-backed API,
 * never a projected or pending figure dressed up as real.
 */
export function PaymentsView() {
  const t = useTranslations("payments");
  const { status, accessToken } = useAuth();

  const [subs, setSubs] = useState<SubscriptionStatus[] | null>(null);
  const [payments, setPayments] = useState<SubscriptionPayment[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) return;
    let cancelled = false;
    async function run() {
      try {
        const [s, p] = await Promise.all([
          subscriptionsApi.mine(accessToken!),
          subscriptionsApi.payments(accessToken!),
        ]);
        if (cancelled) return;
        setSubs(s);
        setPayments(p);
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

  if (status !== "authenticated") {
    return (
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
        <p className="text-[var(--text-secondary)]">{t("signInRequired")}</p>
      </div>
    );
  }

  if (subs === null && !error) {
    return (
      <div className="space-y-3" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-20 animate-pulse rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)]"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-10">
      {error ? (
        <p className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-4 text-sm text-danger-500">
          {error}
        </p>
      ) : null}

      <section>
        <h2 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
          {t("subscriptionsTitle")}
        </h2>
        {subs && subs.length > 0 ? (
          <ul className="mt-4 grid gap-3 sm:grid-cols-2">
            {subs.map((s) => (
              <li
                key={`${s.plan_id}-${s.subscriber_address}`}
                className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-5"
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium text-[var(--text-primary)]">
                    {s.plan?.name ?? t("planFallback", { tier: s.tier })}
                  </p>
                  <SubStatus status={s.status} />
                </div>
                <p className="mt-2 text-sm text-[var(--text-secondary)]">
                  {t("renews", {
                    when: new Date(s.current_period_end).toLocaleDateString(),
                  })}
                </p>
                {s.auto_renew_cancelled ? (
                  <p className="mt-1 text-xs text-warning-500">
                    {t("autoRenewOff")}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-4 rounded-[var(--radius-card)] border border-dashed border-[var(--border-subtle)] p-8 text-center text-sm text-[var(--text-muted)]">
            {t("noSubscriptions")}
          </p>
        )}
      </section>

      <section>
        <h2 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
          {t("historyTitle")}
        </h2>
        {payments && payments.length > 0 ? (
          <div className="mt-4 overflow-x-auto rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
            <table className="w-full min-w-[32rem] text-sm">
              <thead>
                <tr className="border-b border-[var(--border-subtle)] text-xs uppercase tracking-wider text-[var(--text-muted)]">
                  <th className="px-4 py-3 text-start font-medium">{t("col.date")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("col.tx")}</th>
                  <th className="px-4 py-3 text-end font-medium">{t("col.amount")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {payments.map((p) => (
                  <tr key={p.id}>
                    <td className="px-4 py-3 text-[var(--text-secondary)]">
                      {new Date(p.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      <code className="font-mono text-xs text-[var(--text-muted)]">
                        {p.tx_hash.slice(0, 10)}…{p.tx_hash.slice(-8)}
                      </code>
                    </td>
                    <td className="px-4 py-3 text-end font-mono">
                      {p.amount} {p.token_symbol}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-4 rounded-[var(--radius-card)] border border-dashed border-[var(--border-subtle)] p-8 text-center text-sm text-[var(--text-muted)]">
            {t("noPayments")}
          </p>
        )}
      </section>
    </div>
  );
}

function SubStatus({ status }: { status: string }) {
  const t = useTranslations("payments");
  const tone =
    status === "active"
      ? "text-success-500 border-success-500/40"
      : status === "expired"
        ? "text-danger-500 border-danger-500/40"
        : "text-[var(--text-muted)] border-[var(--border-subtle)]";
  return (
    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs ${tone}`}>
      {t(`status.${status}`)}
    </span>
  );
}
