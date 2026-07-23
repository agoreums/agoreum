import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { SiteFooter } from "@/components/layout/site-footer";
import { SiteHeader } from "@/components/layout/site-header";
import { Providers } from "@/components/providers";
import { OrganizationJsonLd } from "@/components/seo/json-ld";
import {
  getDirection,
  localeHreflang,
  locales,
  routing,
  type Locale,
} from "@/i18n/routing";
import { absoluteUrl, siteConfig } from "@/lib/site";
import "@/styles/globals.css";

// `display: swap` keeps text visible during font load; both faces are self-hosted
// by Next at build time, so no third-party font request is made at runtime.
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

/** Pre-render every locale at build time. */
export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

export const viewport: Viewport = {
  themeColor: siteConfig.themeColor,
  colorScheme: "dark light",
  width: "device-width",
  initialScale: 1,
};

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  if (!hasLocale(routing.locales, locale)) return {};

  const t = await getTranslations({ locale, namespace: "metadata" });
  const path = locale === routing.defaultLocale ? "" : `/${locale}`;

  // Every locale advertises every other locale, so search engines can serve the
  // right language and never treat translations as duplicate content.
  const languages = Object.fromEntries(
    locales.map((l) => [
      localeHreflang[l],
      l === routing.defaultLocale ? absoluteUrl("/") : absoluteUrl(`/${l}`),
    ]),
  );

  return {
    metadataBase: new URL(siteConfig.url),
    title: {
      default: t("title"),
      template: t("titleTemplate"),
    },
    description: t("description"),
    keywords: t("keywords").split(",").map((k) => k.trim()),
    applicationName: siteConfig.name,
    manifest: "/site.webmanifest",
    alternates: {
      canonical: absoluteUrl(path || "/"),
      languages: { ...languages, "x-default": absoluteUrl("/") },
    },
    icons: {
      icon: [
        { url: "/favicon.ico", sizes: "any" },
        { url: "/icons/favicon-16x16.png", sizes: "16x16", type: "image/png" },
        { url: "/icons/favicon-32x32.png", sizes: "32x32", type: "image/png" },
      ],
      apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180" }],
    },
    openGraph: {
      type: "website",
      siteName: siteConfig.name,
      title: t("title"),
      description: t("description"),
      url: absoluteUrl(path || "/"),
      locale: localeHreflang[locale as Locale],
      images: [
        {
          url: "/icons/og-image.png",
          width: 1200,
          height: 630,
          alt: `${siteConfig.name} — ${t("title")}`,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: t("title"),
      description: t("description"),
      images: ["/icons/twitter-image.png"],
    },
    robots: {
      index: true,
      follow: true,
      googleBot: { index: true, follow: true, "max-image-preview": "large" },
    },
  };
}

export default async function LocaleLayout(props: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  if (!hasLocale(routing.locales, locale)) {
    notFound();
  }

  // Required for static rendering of a locale-aware tree.
  setRequestLocale(locale);

  const t = await getTranslations("nav");

  return (
    <html
      lang={localeHreflang[locale]}
      dir={getDirection(locale)}
      suppressHydrationWarning
    >
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} min-h-dvh antialiased`}
      >
        <NextIntlClientProvider>
          <Providers>
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
          </Providers>
        </NextIntlClientProvider>
        <OrganizationJsonLd />
      </body>
    </html>
  );
}
