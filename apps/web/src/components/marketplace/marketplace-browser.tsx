import { getTranslations } from "next-intl/server";

import { SearchControls } from "@/components/marketplace/search-controls";
import { ServiceCard } from "@/components/marketplace/service-card";
import { Link } from "@/i18n/navigation";
import { ApiError, marketplaceApi } from "@/lib/api";

/**
 * The marketplace, as one implementation.
 *
 * Search, results, filters, pagination, and the honest empty and unavailable
 * states all live here. The public marketplace and the in-app marketplace both
 * render this, differing only in the `basePath` used to build pagination links and
 * in the chrome their page wraps around it, so there is never a second catalogue
 * to keep in step.
 */
type SearchParams = Record<string, string | string[] | undefined>;

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

const PAGE_SIZE = 24;

export async function MarketplaceBrowser({
  locale,
  searchParams,
  basePath,
}: {
  locale: string;
  searchParams: SearchParams;
  basePath: string;
}) {
  const t = await getTranslations("marketplace");

  const offset = Number(firstValue(searchParams.offset) ?? 0) || 0;
  const query = {
    q: firstValue(searchParams.q),
    category: firstValue(searchParams.category),
    tags: firstValue(searchParams.tags),
    sort: firstValue(searchParams.sort) ?? "relevance",
    verification_tier: firstValue(searchParams.verification_tier),
    max_price: firstValue(searchParams.max_price),
    min_rating: firstValue(searchParams.min_rating),
    limit: PAGE_SIZE,
    offset,
    facets: "true",
  };

  // The API is a separate process and can legitimately be unavailable. That is
  // reported as an error state rather than rendered as "no results".
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
      <p
        role="alert"
        className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-6 text-sm leading-relaxed text-[var(--text-secondary)]"
      >
        {t("unavailable")}
      </p>
    );
  }

  const showingFrom = results.total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + results.items.length, results.total);

  return (
    <div>
      <SearchControls categories={categories} filters={filters} />

      <p aria-live="polite" className="mt-6 text-sm text-[var(--text-muted)]">
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

      {results.total > PAGE_SIZE ? (
        <Pagination
          offset={offset}
          limit={PAGE_SIZE}
          total={results.total}
          searchParams={searchParams}
          basePath={basePath}
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
  basePath,
  previousLabel,
  nextLabel,
}: {
  offset: number;
  limit: number;
  total: number;
  searchParams: SearchParams;
  basePath: string;
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
    return qs ? `${basePath}?${qs}` : basePath;
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
