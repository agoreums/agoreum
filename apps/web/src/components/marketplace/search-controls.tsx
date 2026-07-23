"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useCallback, useState, useTransition } from "react";

import { usePathname, useRouter } from "@/i18n/navigation";
import type { Category, FilterMetadata } from "@/lib/api";

/**
 * Search and filter controls.
 *
 * State lives entirely in the URL rather than in React state. That makes every
 * result set linkable and shareable, keeps the back button meaningful, and lets
 * the page stay a server component that reads its filters from searchParams.
 */
export function SearchControls({
  categories,
  filters,
}: {
  categories: Category[];
  filters: FilterMetadata;
}) {
  const t = useTranslations("marketplace");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [isPending, startTransition] = useTransition();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");

  const applyParams = useCallback(
    (changes: Record<string, string | null>) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
      }
      // Any filter change invalidates the current page position.
      next.delete("offset");

      startTransition(() => {
        router.replace(`${pathname}?${next.toString()}`, { scroll: false });
      });
    },
    [pathname, router, searchParams],
  );

  const activeCategory = searchParams.get("category") ?? "";
  const activeSort = searchParams.get("sort") ?? "relevance";
  const activeTier = searchParams.get("verification_tier") ?? "";
  const activeTag = searchParams.get("tags") ?? "";

  const hasActiveFilters =
    Boolean(activeCategory || activeTier || activeTag) ||
    Boolean(searchParams.get("max_price")) ||
    Boolean(searchParams.get("q"));

  return (
    <div className="space-y-4">
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          applyParams({ q: query.trim() || null });
        }}
        className="flex gap-2"
      >
        <div className="relative flex-1">
          <label htmlFor="marketplace-search" className="sr-only">
            {t("searchLabel")}
          </label>
          <input
            id="marketplace-search"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("searchPlaceholder")}
            className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-raised)] px-4 py-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus-visible:border-brand-400"
          />
        </div>
        <button
          type="submit"
          disabled={isPending}
          className="rounded-xl bg-brand-600 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-brand-500 disabled:opacity-60"
        >
          {t("searchAction")}
        </button>
      </form>

      <div className="flex flex-wrap items-center gap-2">
        <FilterSelect
          label={t("filters.category")}
          value={activeCategory}
          onChange={(v) => applyParams({ category: v || null })}
          options={[
            { value: "", label: t("filters.allCategories") },
            ...categories.flatMap((parent) => [
              { value: parent.slug, label: parent.name },
              ...(parent.children ?? []).map((child) => ({
                value: child.slug,
                label: `  ${child.name}`,
              })),
            ]),
          ]}
        />

        <FilterSelect
          label={t("filters.sort")}
          value={activeSort}
          onChange={(v) => applyParams({ sort: v })}
          options={filters.sorts.map((s) => ({
            value: s,
            label: t(`sorts.${s}`),
          }))}
        />

        <FilterSelect
          label={t("filters.verification")}
          value={activeTier}
          onChange={(v) => applyParams({ verification_tier: v || null })}
          options={[
            { value: "", label: t("filters.anyProvider") },
            { value: "domain_verified", label: t("verification.domain") },
            {
              value: "organization_verified",
              label: t("verification.organization"),
            },
          ]}
        />

        {/* Only offered when tags genuinely exist in the catalogue. */}
        {filters.tags.length > 0 ? (
          <FilterSelect
            label={t("filters.tag")}
            value={activeTag}
            onChange={(v) => applyParams({ tags: v || null })}
            options={[
              { value: "", label: t("filters.anyTag") },
              ...filters.tags.map((t2) => ({
                value: t2.tag,
                label: `${t2.tag} (${t2.count})`,
              })),
            ]}
          />
        ) : null}

        {hasActiveFilters ? (
          <button
            type="button"
            onClick={() => {
              setQuery("");
              startTransition(() => router.replace(pathname, { scroll: false }));
            }}
            className="rounded-lg px-3 py-2 text-sm text-[var(--text-secondary)] underline-offset-4 transition-colors hover:text-[var(--text-primary)] hover:underline"
          >
            {t("filters.clear")}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="inline-flex items-center gap-2">
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="cursor-pointer rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-raised)] px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
