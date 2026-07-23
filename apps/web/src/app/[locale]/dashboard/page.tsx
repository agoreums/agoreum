import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { DashboardView } from "@/components/dashboard/dashboard-view";

// Personal data, and never useful to a crawler.
export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  const t = await getTranslations({ locale, namespace: "dashboard" });

  return {
    title: t("title"),
    // Excluded in robots.txt as well; this is belt and braces.
    robots: { index: false, follow: false },
  };
}

export default async function DashboardPage(props: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  const t = await getTranslations("dashboard");

  return (
    <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
      <header className="max-w-2xl">
        <h1 className="text-[length:var(--text-h1)] font-semibold leading-[var(--text-h1--line-height)] tracking-[var(--text-h1--letter-spacing)]">
          {t("title")}
        </h1>
        <p className="mt-3 text-pretty leading-relaxed text-[var(--text-secondary)]">
          {t("subtitle")}
        </p>
      </header>

      <div className="mt-10">
        <DashboardView />
      </div>
    </div>
  );
}
