"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { analyticsApi, ApiError, type CreatorAnalytics } from "@/lib/api";

/**
 * Creator analytics.
 *
 * Every figure is the API's own count of settled activity and real pageviews.
 * Where a value cannot be known, views when the source is unavailable, a
 * conversion rate with no visits, it is shown as "not available" rather than a
 * fabricated zero, because an absent measurement and a measured zero differ.
 */
export function AnalyticsView() {
  const t = useTranslations("analytics");
  const { status, accessToken } = useAuth();

  const [data, setData] = useState<CreatorAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) return;
    let cancelled = false;
    async function run() {
      try {
        const a = await analyticsApi.me(accessToken!);
        if (!cancelled) {
          setData(a);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t("loadFailed"));
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
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-hidden="true">
        {[0, 1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="h-24 animate-pulse rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)]"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <p role="alert" className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-6 text-sm text-danger-500">
        {error}
      </p>
    );
  }

  if (!data) return null;

  const views = data.views === null ? t("notAvailable") : formatCount(data.views);
  const conversion =
    data.conversion_rate === null
      ? t("notAvailable")
      : `${(data.conversion_rate * 100).toFixed(1)}%`;

  return (
    <div className="space-y-6">
      <p className="text-xs text-[var(--text-muted)]">
        {t("window", { days: data.window_days })}
      </p>

      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Stat label={t("views")} value={views} hint={t("viewsHint")} />
        <Stat label={t("purchases")} value={formatCount(data.purchases)} />
        <Stat
          label={t("revenue")}
          value={`${formatAmount(data.revenue)} ${data.currency}`}
          hint={t("settledOnly")}
        />
        <Stat label={t("repeatCustomers")} value={formatCount(data.repeat_customers)} />
        <Stat label={t("conversion")} value={conversion} />
      </dl>

      {data.views_series && data.views_series.length > 1 ? (
        <div className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-5">
          <p className="text-xs text-[var(--text-muted)]">{t("viewsOverTime")}</p>
          <Sparkline series={data.views_series} />
        </div>
      ) : null}
    </div>
  );
}

function Sparkline({ series }: { series: { date: string; views: number }[] }) {
  const max = Math.max(1, ...series.map((p) => p.views));
  return (
    <div
      className="mt-3 flex h-20 items-end gap-0.5"
      role="img"
      aria-label={`${series.length} days of views`}
    >
      {series.map((point) => (
        <div
          key={point.date}
          title={`${point.date}: ${point.views}`}
          className="flex-1 rounded-sm bg-brand-500/70"
          style={{ height: `${Math.max(4, (point.views / max) * 100)}%` }}
        />
      ))}
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-5">
      <dt className="text-xs text-[var(--text-muted)]">{label}</dt>
      <dd className="mt-1.5 font-mono text-xl text-[var(--text-primary)]">{value}</dd>
      {hint ? (
        <p className="mt-1.5 text-[0.6875rem] leading-relaxed text-[var(--text-muted)]">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function formatAmount(value: string): string {
  const amount = Number(value);
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: amount < 1 ? 6 : 2,
  }).format(amount);
}

function formatCount(value: number): string {
  return new Intl.NumberFormat(undefined).format(value);
}
