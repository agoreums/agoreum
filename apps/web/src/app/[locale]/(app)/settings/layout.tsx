import { getTranslations, setRequestLocale } from "next-intl/server";
import type { ReactNode } from "react";

import { SettingsNav } from "@/components/settings/settings-nav";

/**
 * The settings section. One tab bar wraps every settings screen so the whole area
 * reads as a single, coherent place; each screen supplies its own title beneath.
 */
export default async function SettingsLayout(props: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  const t = await getTranslations("settings");

  return (
    <div className="space-y-8">
      <p className="text-xs font-medium uppercase tracking-wider text-[var(--text-muted)]">
        {t("title")}
      </p>
      <SettingsNav />
      <div>{props.children}</div>
    </div>
  );
}
