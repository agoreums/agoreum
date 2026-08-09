import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { PageHeader } from "@/components/app/page-header";
import { DisputeQueueView } from "@/components/admin/dispute-queue-view";

/**
 * The arbiter's queue.
 *
 * Not linked from the main navigation: it is useful to exactly one account, and
 * the API refuses everybody else regardless of who finds the page.
 */
export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  const t = await getTranslations({ locale, namespace: "arbiter" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

export default async function ArbiterPage(props: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);
  const t = await getTranslations("arbiter");

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} description={t("subtitle")} />
      <DisputeQueueView />
    </div>
  );
}
