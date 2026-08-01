import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { PageHeader } from "@/components/app/page-header";
import { MarketplaceBrowser } from "@/components/marketplace/marketplace-browser";

// Live results, and part of the private app rather than public content.
export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  const t = await getTranslations({ locale, namespace: "marketplace" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

type SearchParams = Record<string, string | string[] | undefined>;

export default async function BrowsePage(props: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  const searchParams = await props.searchParams;
  const t = await getTranslations("marketplace");

  return (
    <div className="space-y-8">
      <PageHeader title={t("title")} description={t("subtitle")} />
      <MarketplaceBrowser
        locale={locale}
        searchParams={searchParams}
        basePath="/browse"
      />
    </div>
  );
}
