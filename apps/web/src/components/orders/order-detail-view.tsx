"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { DisputePanel } from "@/components/orders/dispute-panel";
import { SettlementActions } from "@/components/orders/settlement-actions";
import { PageHeader } from "@/components/app/page-header";
import { Skeleton } from "@/components/app/ui";
import { ApiError, ordersApi, type OrderDetail } from "@/lib/api";

/**
 * One order, its escrow, and every exit from it.
 *
 * The orders page was a flat table with nothing behind it, so there was nowhere
 * to put a dispute, a refund, or a receipt. `DisputePanel` had been built and
 * translated into nine languages and was rendered by no page at all.
 */
export function OrderDetailView({ orderId }: { orderId: string }) {
  const t = useTranslations("orders");
  const statusLabel = useTranslations("dashboard.status");
  const { status, accessToken } = useAuth();

  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (status === "loading") return;
    let cancelled = false;
    if (!accessToken) {
      void Promise.resolve().then(() => {
        if (!cancelled) setLoading(false);
      });
      return () => {
        cancelled = true;
      };
    }
    void ordersApi
      .get(accessToken, orderId)
      .then((next) => {
        if (!cancelled) setOrder(next);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : t("detail.loadFailed"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [status, accessToken, orderId, t]);

  if (loading) return <Skeleton className="h-64" />;

  if (error || !order) {
    return (
      <p className="rounded-[var(--radius-card)] border border-dashed border-[var(--border-subtle)] p-10 text-center text-sm text-[var(--text-muted)]">
        {error ?? t("detail.notFound")}
      </p>
    );
  }

  const escrow = order.escrow;

  return (
    <div className="space-y-8">
      <PageHeader
        title={order.reference}
        description={statusLabel(order.status)}
      />

      <section className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-5">
        <h2 className="text-sm font-medium text-[var(--text-primary)]">
          {t("detail.summary")}
        </h2>
        <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <Row label={t("col.amount")} value={`${order.total_amount} ${order.currency}`} />
          <Row label={t("detail.placed")} value={new Date(order.created_at).toLocaleString()} />
          {escrow ? (
            <>
              <Row label={t("detail.escrowStatus")} value={escrow.status} />
              <Row label={t("detail.released")} value={escrow.released_amount} />
              <Row label={t("detail.refunded")} value={escrow.refunded_amount} />
              <Row label={t("detail.fee")} value={escrow.fee_amount} />
            </>
          ) : null}
        </dl>
      </section>

      {/* Every exit the contract allows, whether or not it is open right now. */}
      <SettlementActions orderId={order.id} />

      <DisputePanel orderId={order.id} />
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-[var(--border-subtle)] py-1.5">
      <dt className="text-[var(--text-muted)]">{label}</dt>
      <dd className="font-mono text-[var(--text-primary)]">{value}</dd>
    </div>
  );
}
