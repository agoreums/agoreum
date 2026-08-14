import type { Metadata } from "next";

import type { Locale } from "@/i18n/routing";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { MarketplaceBrowser } from "@/components/marketplace/marketplace-browser";
import { localizedAlternates, socialCard } from "@/lib/site";

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
    alternates: localizedAlternates(locale as Locale, "/marketplace"),
    ...socialCard({
      locale: locale as Locale,
      path: "/marketplace",
      title: t("title"),
      description: t("metaDescription"),
    }),
  };
}

type SearchParams = Record<string, string | string[] | undefined>;

export default async function MarketplacePage(props: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  const searchParams = await props.searchParams;
  const t = await getTranslations("marketplace");

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
        <MarketplaceBrowser
          locale={locale}
          searchParams={searchParams}
          basePath="/marketplace"
        />
      </div>
    </div>
  );
}
