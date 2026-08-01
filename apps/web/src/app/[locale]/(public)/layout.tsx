import { getTranslations, setRequestLocale } from "next-intl/server";
import type { ReactNode } from "react";

import { CookieConsent } from "@/components/layout/cookie-consent";
import { SiteFooter } from "@/components/layout/site-footer";
import { SiteHeader } from "@/components/layout/site-header";
import { OrganizationJsonLd } from "@/components/seo/json-ld";
import { locales } from "@/i18n/routing";

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

/**
 * The public marketing site: header, footer, and the cookie banner. Everything a
 * visitor sees before signing in lives under this group. The authenticated app is
 * a separate group with its own shell, so its chrome never appears here and this
 * chrome never appears there.
 */
export default async function PublicLayout(props: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  const t = await getTranslations("nav");

  return (
    <>
      <a href="#main" className="skip-link">
        {t("skipToContent")}
      </a>
      <div className="flex min-h-dvh flex-col">
        <SiteHeader />
        <main id="main" className="flex-1">
          {props.children}
        </main>
        <SiteFooter />
      </div>
      <CookieConsent />
      <OrganizationJsonLd />
    </>
  );
}
