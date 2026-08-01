import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { PageHeader } from "@/components/app/page-header";
import { ApiKeysView } from "@/components/settings/api-keys-view";

// Personal, credential-bearing, and never useful to a crawler.
export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  const t = await getTranslations({ locale, namespace: "apiKeys" });

  return {
    title: t("title"),
    robots: { index: false, follow: false },
  };
}

export default async function ApiKeysPage(props: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  const t = await getTranslations("apiKeys");

  return (
    <div className="space-y-8">
      <PageHeader title={t("title")} description={t("subtitle")} />
      <ApiKeysView />
    </div>
  );
}
