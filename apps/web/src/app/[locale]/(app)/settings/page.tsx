import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { Icon, type IconKey } from "@/components/app/icons";
import { PageHeader } from "@/components/app/page-header";
import { Link } from "@/i18n/navigation";

// Personal, session-bound, and never useful to a crawler.
export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  const t = await getTranslations({ locale, namespace: "settings" });

  return {
    title: t("title"),
    robots: { index: false, follow: false },
  };
}

const areas: { key: string; href: string; icon: IconKey }[] = [
  { key: "organizations", href: "/settings/organizations", icon: "organizations" },
  { key: "apiKeys", href: "/settings/api-keys", icon: "key" },
  { key: "webhooks", href: "/settings/webhooks", icon: "webhook" },
];

export default async function SettingsPage(props: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  const t = await getTranslations("settings");

  return (
    <div className="space-y-8">
      <PageHeader title={t("title")} description={t("subtitle")} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {areas.map((area) => (
          <Link
            key={area.href}
            href={area.href}
            className="group rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-5 transition-colors hover:border-brand-500"
          >
            <span className="grid size-10 place-items-center rounded-xl bg-brand-500/10 text-brand-500">
              <Icon name={area.icon} size={20} />
            </span>
            <h2 className="mt-4 text-sm font-semibold text-[var(--text-primary)]">
              {t(`areas.${area.key}.title`)}
            </h2>
            <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
              {t(`areas.${area.key}.description`)}
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}
