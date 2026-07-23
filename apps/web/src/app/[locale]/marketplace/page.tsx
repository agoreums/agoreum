import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { SearchControls } from "@/components/marketplace/search-controls";
import { ServiceCard } from "@/components/marketplace/service-card";
import { Link } from "@/i18n/navigation";
import { ApiError, marketplaceApi } from "@/lib/api";
import { absoluteUrl } from "@/lib/site";

// Results depend on live data, so this must not be statically cached.
export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  const t = await getTranslations({ locale, namespace: "marketplace" });

  return {
    title: t("title"),
    description: t("metaDescription"),
    alternates: { canonical: absoluteUrl("/marketplace") },
  };
}

type SearchParams = Record<string, string | string[] | undefined>;

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function MarketplacePage(props: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  const searchParams = await props.searchParams;
  const t = await getTranslations("marketplace");

  const offset = Number(firstValue(searchParams.offset) ?? 0) || 0;
  const limit = 24;

  const query = {
    q: firstValue(searchParams.q),
    category: firstValue(searchParams.category),
    tags: firstValue(searchParams.tags),
    sort: firstValue(searchParams.sort) ?? "relevance",
    verification_tier: firstValue(searchParams.verification_tier),
    max_price: firstValue(searchParams.max_price),
    min_rating: firstValue(searchParams.min_rating),
    limit,
    offset,
    facets: "true",
  };

  // The API is a separate process and can legitimately be unavailable. That is
  // reported as an error state rather than rendered as "no results", which
  // would tell the user something false about the marketplace.
  let results = null;
  let categories: Awaited<ReturnType<typeof marketplaceApi.categories>> = [];
  let filters: Awaited<ReturnType<typeof marketplaceApi.filters>> | null = null;
  let unavailable = false;

  try {
    [results, categories, filters] = await Promise.all([
      marketplaceApi.searchServices(query),
      marketplaceApi.categories(),
      marketplaceApi.filters(),
    ]);
  } catch (error) {
    unavailable = true;
    if (!(error instanceof ApiError)) {
      console.error("marketplace fetch failed", error);
    }
  }

  if (unavailable || !results || !filters) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <h1 className="text-[length:var(--text-h1)] font-semibold tracking-[var(--text-h1--letter-spacing)]">
          {t("title")}
        </h1>
        <p
          role="alert"
          className="mt-6 rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-6 text-sm leading-relaxed text-[var(--text-secondary)]"
        >
          {t("unavailable")}
        </p>
      </div>
    );
  }

  const showingFrom = results.total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + results.items.length, results.total);

  return (
    <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
      <header className="max-w-2xl">
        <h1 className="text-[length:var(--text-h1)] font-semibold leading-[var(--text-h1--line-height)] tracking-[var(--text-h1--letter-spacing)]">
          {t("title")}
        </h1>
        <p className="mt-4 text-pretty leading-relaxed text-[var(--text-secondary)]">
          {t("subtitle")}
        </p>
      </header>

      <div className="mt-10">
        <SearchControls categories={categories} filters={filters} />
      </div>

      <p
        aria-live="polite"
        className="mt-6 text-sm text-[var(--text-muted)]"
      >
        {results.total === 0
          ? t("resultsNone")
          : t("resultsRange", {
              from: showingFrom,
              to: showingTo,
              total: results.total,
            })}
      </p>

      {results.items.length > 0 ? (
        <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {results.items.map((service) => (
            <li key={service.id}>
              <ServiceCard service={service} locale={locale} />
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          hasQuery={Boolean(query.q || query.category || query.tags)}
          t={t}
        />
      )}

      {results.total > limit ? (
        <Pagination
          offset={offset}
          limit={limit}
          total={results.total}
          searchParams={searchParams}
          previousLabel={t("pagination.previous")}
          nextLabel={t("pagination.next")}
        />
      ) : null}
    </div>
  );
}

function EmptyState({
  hasQuery,
  t,
}: {
  hasQuery: boolean;
  t: Awaited<ReturnType<typeof getTranslations<"marketplace">>>;
}) {
  return (
    <div className="mt-6 rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-12 text-center">
      <p className="text-[var(--text-secondary)]">
        {hasQuery ? t("noMatches") : t("catalogueEmpty")}
      </p>
      {!hasQuery ? (
        <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-[var(--text-muted)]">
          {/* Said plainly. An empty marketplace is not disguised with
              placeholder listings. */}
          {t("catalogueEmptyDetail")}
        </p>
      ) : null}
      <Link
        href="/agents/register"
        className="mt-6 inline-flex rounded-xl border border-[var(--border-strong)] px-5 py-2.5 text-sm font-medium transition-colors hover:bg-[var(--surface-raised)]"
      >
        {t("registerCta")}
      </Link>
    </div>
  );
}

function Pagination({
  offset,
  limit,
  total,
  searchParams,
  previousLabel,
  nextLabel,
}: {
  offset: number;
  limit: number;
  total: number;
  searchParams: SearchParams;
  previousLabel: string;
  nextLabel: string;
}) {
  const buildHref = (nextOffset: number) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(searchParams)) {
      const single = Array.isArray(value) ? value[0] : value;
      if (single && key !== "offset") params.set(key, single);
    }
    if (nextOffset > 0) params.set("offset", String(nextOffset));
    const qs = params.toString();
    return qs ? `/marketplace?${qs}` : "/marketplace";
  };

  const hasPrevious = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <nav
      aria-label="Pagination"
      className="mt-10 flex items-center justify-between border-t border-[var(--border-subtle)] pt-6"
    >
      {hasPrevious ? (
        <Link
          href={buildHref(Math.max(0, offset - limit))}
          className="rounded-lg border border-[var(--border-subtle)] px-4 py-2 text-sm transition-colors hover:bg-[var(--surface-raised)]"
        >
          ← {previousLabel}
        </Link>
      ) : (
        <span />
      )}
      {hasNext ? (
        <Link
          href={buildHref(offset + limit)}
          className="rounded-lg border border-[var(--border-subtle)] px-4 py-2 text-sm transition-colors hover:bg-[var(--surface-raised)]"
        >
          {nextLabel} →
        </Link>
      ) : (
        <span />
      )}
    </nav>
  );
}
