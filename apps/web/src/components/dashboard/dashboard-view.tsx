"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { Link } from "@/i18n/navigation";
import {
  ApiError,
  dashboardApi,
  type BuyerDashboard,
  type ProviderDashboard,
} from "@/lib/api";

type Tab = "buyer" | "provider";

/**
 * Buyer and provider dashboards.
 *
 * Every figure comes from the API's count of real rows. Where a value is null
 * the interface says "nothing yet" rather than rendering a zero, because a
 * measured zero and an absent measurement mean different things — particularly
 * for earnings and ratings.
 */
export function DashboardView() {
  const t = useTranslations("dashboard");
  const { status, accessToken } = useAuth();

  const [tab, setTab] = useState<Tab>("buyer");
  const [buyer, setBuyer] = useState<BuyerDashboard | null>(null);
  const [provider, setProvider] = useState<ProviderDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // `loading` starts true and is only cleared once the request settles, so the
  // effect never sets state synchronously on the render path. Fetching is
  // genuinely asynchronous, and modelling it that way avoids a cascading render.
  useEffect(() => {
    if (status !== "authenticated" || !accessToken) return;

    let cancelled = false;

    async function load() {
      try {
        const [b, p] = await Promise.all([
          dashboardApi.buyer(accessToken!),
          dashboardApi.provider(accessToken!),
        ]);
        if (cancelled) return;
        setBuyer(b);
        setProvider(p);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : t("loadFailed"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [status, accessToken, t]);

  if (status === "loading") {
    return <p className="text-[var(--text-muted)]">{t("loading")}</p>;
  }

  if (status !== "authenticated") {
    return (
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
        <p className="text-[var(--text-secondary)]">{t("signInRequired")}</p>
      </div>
    );
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

  if (loading || !buyer || !provider) {
    return <p className="text-[var(--text-muted)]">{t("loading")}</p>;
  }

  return (
    <div>
      <div
        role="tablist"
        aria-label={t("title")}
        className="flex gap-1 border-b border-[var(--border-subtle)]"
      >
        {(["buyer", "provider"] as const).map((key) => (
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

      <div className="mt-8">
        {tab === "buyer" ? (
          <BuyerPanel data={buyer} />
        ) : (
          <ProviderPanel data={provider} />
        )}
      </div>
    </div>
  );
}

function BuyerPanel({ data }: { data: BuyerDashboard }) {
  const t = useTranslations("dashboard");

  return (
    <div className="space-y-8">
      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t("buyer.activeOrders")} value={data.active_orders} />
        <Stat label={t("buyer.completed")} value={data.completed_orders} />
        <Stat
          label={t("buyer.totalSpent")}
          value={`${formatAmount(data.total_spent)} ${data.currency}`}
          hint={t("buyer.settledOnly")}
        />
        <Stat
          label={t("buyer.awaitingReview")}
          value={data.awaiting_review}
          highlight={data.awaiting_review > 0}
        />
      </dl>

      <RecentOrders orders={data.recent_orders} emptyLabel={t("buyer.noOrders")} />
    </div>
  );
}

function ProviderPanel({ data }: { data: ProviderDashboard }) {
  const t = useTranslations("dashboard");

  if (data.agents === 0) {
    return (
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
        <p className="text-[var(--text-secondary)]">{t("provider.noAgents")}</p>
        <Link
          href="/agents/register"
          className="mt-5 inline-flex rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-500"
        >
          {t("provider.registerCta")}
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label={t("provider.awaitingAction")}
          value={data.awaiting_action}
          highlight={data.awaiting_action > 0}
        />
        <Stat label={t("provider.completed")} value={data.completed_orders} />
        <Stat
          label={t("provider.earned")}
          // Null means nothing has settled, which is not the same as zero.
          value={
            data.total_earned === null
              ? t("nothingYet")
              : `${formatAmount(data.total_earned)} ${data.currency}`
          }
          hint={t("provider.releasedOnly")}
        />
        <Stat
          label={t("provider.rating")}
          value={
            data.average_rating === null
              ? t("notRatedYet")
              : `${data.average_rating.toFixed(1)} (${data.review_count})`
          }
        />
      </dl>

      <dl className="grid gap-4 sm:grid-cols-3">
        <Stat label={t("provider.agents")} value={data.agents} />
        <Stat label={t("provider.published")} value={data.published_agents} />
        <Stat label={t("provider.services")} value={data.published_services} />
      </dl>

      <RecentOrders
        orders={data.recent_orders}
        emptyLabel={t("provider.noOrders")}
      />
    </div>
  );
}

function RecentOrders({
  orders,
  emptyLabel,
}: {
  orders: BuyerDashboard["recent_orders"];
  emptyLabel: string;
}) {
  const t = useTranslations("dashboard");

  return (
    <section>
      <h2 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
        {t("recentOrders")}
      </h2>

      {orders.length === 0 ? (
        <p className="mt-4 rounded-[var(--radius-card)] border border-dashed border-[var(--border-subtle)] p-8 text-center text-sm text-[var(--text-muted)]">
          {emptyLabel}
        </p>
      ) : (
        <ul className="mt-4 divide-y divide-[var(--border-subtle)] rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
          {orders.map((order) => (
            <li
              key={order.id}
              className="flex flex-wrap items-center justify-between gap-3 px-5 py-4"
            >
              <div>
                <p className="font-mono text-sm">{order.reference}</p>
                <p className="mt-0.5 text-xs text-[var(--text-muted)]">
                  {new Date(order.created_at).toLocaleDateString()}
                </p>
              </div>
              <div className="flex items-center gap-4">
                <span className="font-mono text-sm">
                  {formatAmount(order.total_amount)} {order.currency}
                </span>
                <StatusChip status={order.status} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function StatusChip({ status }: { status: string }) {
  const t = useTranslations("dashboard.status");

  const tone =
    status === "completed"
      ? "text-success-500"
      : status === "disputed"
        ? "text-danger-500"
        : status === "pending_payment"
          ? "text-warning-500"
          : "text-[var(--text-secondary)]";

  return (
    <span
      className={`rounded-md border border-[var(--border-subtle)] px-2 py-0.5 text-xs ${tone}`}
    >
      {t(status)}
    </span>
  );
}

function Stat({
  label,
  value,
  hint,
  highlight = false,
}: {
  label: string;
  value: string | number;
  hint?: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-[var(--radius-card)] border p-5 ${
        highlight
          ? "border-brand-500/40 bg-brand-500/5"
          : "border-[var(--border-subtle)]"
      }`}
    >
      <dt className="text-xs text-[var(--text-muted)]">{label}</dt>
      <dd className="mt-1.5 font-mono text-xl text-[var(--text-primary)]">
        {value}
      </dd>
      {hint ? (
        <p className="mt-1.5 text-[0.6875rem] leading-relaxed text-[var(--text-muted)]">
          {hint}
        </p>
      ) : null}
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
