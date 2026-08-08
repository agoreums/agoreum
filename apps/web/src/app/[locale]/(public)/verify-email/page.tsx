import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { PageShell } from "@/components/layout/page-shell";
import { VerifyEmailView } from "@/components/settings/verify-email-view";

/**
 * The page every confirmation link points at.
 *
 * Public rather than behind the app shell, because the link is opened from an
 * inbox, which is frequently a different browser from the one holding the
 * session. The API endpoint is unauthenticated for the same reason: the token
 * carried in the link is the proof, not a cookie.
 */
export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  const t = await getTranslations({ locale, namespace: "verifyEmail" });
  return {
    title: t("title"),
    // Never indexed. The URL carries a single-use credential in its query string.
    robots: { index: false, follow: false },
  };
}

export default async function VerifyEmailPage(props: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);
  const t = await getTranslations("verifyEmail");

  return (
    <PageShell title={t("title")} lede={t("lede")}>
      {/* useSearchParams needs a boundary; the token is only readable client side. */}
      <Suspense fallback={null}>
        <VerifyEmailView />
      </Suspense>
    </PageShell>
  );
}
