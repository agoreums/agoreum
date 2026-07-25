"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Link } from "@/i18n/navigation";
import {
  marketplaceApi,
  type Category,
  type ServiceListItem,
} from "@/lib/api";

import { Reveal, Stagger, StaggerItem } from "./motion";

/**
 * Marketplace showcase.
 *
 * Renders real listings fetched live from the API — never a static mockup and
 * never invented data. If the marketplace has no published services yet, it says
 * so plainly and shows the real category taxonomy instead of pretending otherwise.
 */
export function MarketplaceShowcase() {
  const t = useTranslations("home");
  const [services, setServices] = useState<ServiceListItem[] | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [results, cats] = await Promise.all([
          marketplaceApi.searchServices({ limit: 6, sort: "newest" }),
          marketplaceApi.categories(),
        ]);
        if (cancelled) return;
        setServices(results.items);
        setTotal(results.total);
        setCategories(cats);
      } catch {
        if (!cancelled) setServices([]);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const hasServices = services !== null && services.length > 0;

  return (
    <section
      aria-labelledby="showcase-heading"
      className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8"
    >
      <Reveal>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2
              id="showcase-heading"
              className="max-w-2xl text-balance text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2--line-height)] tracking-[var(--text-h2--letter-spacing)]"
            >
              {t("showcase.title")}
            </h2>
            <p className="mt-4 max-w-2xl text-pretty leading-relaxed text-[var(--text-secondary)]">
              {t("showcase.subtitle")}
            </p>
          </div>
          <Link
            href="/marketplace"
            className="inline-flex shrink-0 items-center justify-center rounded-xl border border-[var(--border-strong)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] transition-colors hover:bg-[var(--surface-raised)]"
          >
            {t("showcase.browse")}
          </Link>
        </div>
      </Reveal>

      {services === null ? (
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-40 animate-pulse rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)]"
            />
          ))}
        </div>
      ) : hasServices ? (
        <Stagger className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {services.map((service) => (
            <StaggerItem key={service.id}>
              <PreviewCard service={service} />
            </StaggerItem>
          ))}
        </Stagger>
      ) : (
        <EmptyState categories={categories} note={t("showcase.empty")} />
      )}

      {total !== null && total > 0 ? (
        <p className="mt-6 text-sm text-[var(--text-muted)]">
          {t("showcase.count", { count: total })}
        </p>
      ) : null}
    </section>
  );
}

function PreviewCard({ service }: { service: ServiceListItem }) {
  return (
    <Link
      href={`/agents/${service.agent.slug}/services/${service.slug}`}
      className="flex h-full flex-col rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-5 transition-colors hover:border-brand-500"
    >
      <h3 className="line-clamp-1 font-medium text-[var(--text-primary)]">
        {service.title}
      </h3>
      {service.summary ? (
        <p className="mt-1.5 line-clamp-2 text-sm leading-relaxed text-[var(--text-secondary)]">
          {service.summary}
        </p>
      ) : null}
      <div className="mt-4 flex items-center justify-between text-xs text-[var(--text-muted)]">
        <span>{service.agent.name}</span>
        {service.price ? (
          <span className="font-mono text-[var(--text-secondary)]">
            {service.price} {service.price_currency}
          </span>
        ) : null}
      </div>
    </Link>
  );
}

function EmptyState({ categories, note }: { categories: Category[]; note: string }) {
  return (
    <div className="mt-12 rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-8 text-center">
      <p className="text-[var(--text-secondary)]">{note}</p>
      {categories.length > 0 ? (
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          {categories.slice(0, 12).map((c) => (
            <span
              key={c.id}
              className="rounded-full border border-[var(--border-subtle)] px-3 py-1 text-xs text-[var(--text-muted)]"
            >
              {c.name}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
