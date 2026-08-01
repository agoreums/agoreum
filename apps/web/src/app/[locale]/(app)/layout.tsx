import { setRequestLocale } from "next-intl/server";
import type { ReactNode } from "react";

import { AppShell } from "@/components/app/app-shell";
import { locales } from "@/i18n/routing";

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

/**
 * The authenticated application. Every route under this group is wrapped in the
 * persistent shell and is never indexed, it is private, session-bound product
 * surface, not public content.
 */
export default async function AppLayout(props: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  return <AppShell>{props.children}</AppShell>;
}
