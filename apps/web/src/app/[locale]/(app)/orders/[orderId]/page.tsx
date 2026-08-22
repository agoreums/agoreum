import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { OrderDetailView } from "@/components/orders/order-detail-view";

// Personal, session-bound, and never useful to a crawler.
export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  const t = await getTranslations({ locale, namespace: "orders" });

  return {
    title: t("detail.title"),
    robots: { index: false, follow: false },
  };
}

/**
 * One order, and everything a party can do about it.
 *
 * There was no per-order page at all before this, which is why `DisputePanel`
 * had been written, translated into nine languages, and rendered by nothing:
 * there was nowhere to put it. The same absence is why the escrow's exits were
 * unreachable.
 */
export default async function OrderDetailPage(props: {
  params: Promise<{ locale: string; orderId: string }>;
}) {
  const { locale, orderId } = await props.params;
  setRequestLocale(locale);

  return <OrderDetailView orderId={orderId} />;
}
