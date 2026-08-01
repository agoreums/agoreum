"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { ApiError, ordersApi, type OrderSummary } from "@/lib/api";

type Tab = "placed" | "received";

/**
 * Orders, split by side.
 *
 * "Placed" are orders the signed-in user bought; "received" are orders placed
 * with agents in the organizations they belong to. Every figure is the API's own
 * record of a real order; nothing here is sample data.
 */
export function OrdersView() {
  const t = useTranslations("orders");
  const { status, accessToken } = useAuth();

  const [tab, setTab] = useState<Tab>("placed");
  const [placed, setPlaced] = useState<OrderSummary[] | null>(null);
  const [received, setReceived] = useState<OrderSummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) return;
    let cancelled = false;
    async function run() {
      try {
        const [p, r] = await Promise.all([
          ordersApi.mine(accessToken!),
          ordersApi.received(accessToken!),
        ]);
        if (cancelled) return;
        setPlaced(p);
        setReceived(r);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : t("loadFailed"));
      } finally {
        if (!cancelled) setLoading(false);
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

  if (loading) {
    return <OrdersSkeleton />;
  }

  if (error) {
    return (
      <p
        role="alert"
        className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-6 text-sm text-danger-500"
      >
        {error}
      </p>
    );
  }

  const orders = tab === "placed" ? placed ?? [] : received ?? [];

  return (
    <div>
      <div
        role="tablist"
        aria-label={t("title")}
        className="flex gap-1 border-b border-[var(--border-subtle)]"
      >
        {(["placed", "received"] as const).map((key) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-4 py-2.5 text-sm transition-colors ${
              tab === key
                ? "border-brand-500 text-[var(--text-primary)]"
                : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            {t(`tabs.${key}`)}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {orders.length === 0 ? (
          <p className="rounded-[var(--radius-card)] border border-dashed border-[var(--border-subtle)] p-10 text-center text-sm text-[var(--text-muted)]">
            {t(`empty.${tab}`)}
          </p>
        ) : (
          <OrderTable orders={orders} />
        )}
      </div>
    </div>
  );
}

function OrderTable({ orders }: { orders: OrderSummary[] }) {
  const t = useTranslations("orders");
  return (
    <div className="overflow-x-auto rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
      <table className="w-full min-w-[36rem] text-sm">
        <thead>
          <tr className="border-b border-[var(--border-subtle)] text-start text-xs uppercase tracking-wider text-[var(--text-muted)]">
            <th className="px-4 py-3 text-start font-medium">{t("col.reference")}</th>
            <th className="px-4 py-3 text-start font-medium">{t("col.status")}</th>
            <th className="px-4 py-3 text-end font-medium">{t("col.amount")}</th>
            <th className="hidden px-4 py-3 text-end font-medium sm:table-cell">
              {t("col.placed")}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--border-subtle)]">
          {orders.map((order) => (
            <tr key={order.id} className="transition-colors hover:bg-[var(--surface-raised)]">
              <td className="px-4 py-3">
                <span className="font-mono text-[var(--text-primary)]">
                  {order.reference}
                </span>
                <span className="mt-0.5 block text-xs text-[var(--text-muted)]">
                  {t("quantity", { count: order.quantity })}
                </span>
              </td>
              <td className="px-4 py-3">
                <StatusChip status={order.status} />
              </td>
              <td className="px-4 py-3 text-end font-mono">
                {formatAmount(order.total_amount)} {order.currency}
              </td>
              <td className="hidden px-4 py-3 text-end text-[var(--text-muted)] sm:table-cell">
                {new Date(order.created_at).toLocaleDateString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  const t = useTranslations("dashboard.status");
  const tone =
    status === "completed"
      ? "text-success-500 border-success-500/40"
      : status === "disputed" || status === "refunded"
        ? "text-danger-500 border-danger-500/40"
        : status === "pending_payment" || status === "expired"
          ? "text-warning-500 border-warning-500/40"
          : "text-[var(--text-secondary)] border-[var(--border-subtle)]";
  return (
    <span className={`inline-block rounded-md border px-2 py-0.5 text-xs ${tone}`}>
      {t(status)}
    </span>
  );
}

function OrdersSkeleton() {
  return (
    <div className="space-y-3" aria-hidden="true">
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="h-14 animate-pulse rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)]"
        />
      ))}
    </div>
  );
}

/** Trims trailing zeros without losing precision that matters. */
function formatAmount(value: string): string {
  const amount = Number(value);
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: amount < 1 ? 6 : 2,
  }).format(amount);
}
