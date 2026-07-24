import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import {
  formatDelivery,
  formatPrice,
} from "@/components/marketplace/service-card";
import { VerificationBadge } from "@/components/marketplace/verification-badge";
import { Link } from "@/i18n/navigation";
import { OrderPaymentPanel } from "@/components/orders/order-payment-panel";
import {
  ApiError,
  marketplaceApi,
  ordersApi,
  type ChainStatus,
  type ServiceDetail,
} from "@/lib/api";
import { absoluteUrl } from "@/lib/site";

export const dynamic = "force-dynamic";

async function loadService(
  agentSlug: string,
  serviceSlug: string,
): Promise<ServiceDetail | null> {
  try {
    return await marketplaceApi.service(agentSlug, serviceSlug);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function generateMetadata(props: {
  params: Promise<{ slug: string; serviceSlug: string }>;
}): Promise<Metadata> {
  const { slug, serviceSlug } = await props.params;
  const service = await loadService(slug, serviceSlug).catch(() => null);

  if (!service) return { title: "Service not found" };

  return {
    title: service.title,
    description: service.summary ?? undefined,
    alternates: {
      canonical: absoluteUrl(`/agents/${slug}/services/${serviceSlug}`),
    },
  };
}

export default async function ServiceDetailPage(props: {
  params: Promise<{ locale: string; slug: string; serviceSlug: string }>;
}) {
  const { locale, slug, serviceSlug } = await props.params;
  setRequestLocale(locale);

  const t = await getTranslations("servicePage");
  const service = await loadService(slug, serviceSlug);
  if (!service) notFound();

  // Whether payment is possible at all is a fact about this environment, not an
  // assumption. If it is unavailable the panel says so rather than offering a
  // button that cannot complete.
  let chainStatus: ChainStatus | null = null;
  try {
    chainStatus = await ordersApi.chainStatus();
  } catch {
    chainStatus = null;
  }

  const price = formatPrice(service, locale);
  const delivery = formatDelivery(service.delivery_time_hours);
  const isAvailable = service.status === "published";

  return (
    <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6 lg:px-8">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "Service",
            name: service.title,
            description: service.summary ?? service.description ?? undefined,
            provider: {
              "@type": "Organization",
              name: service.agent.name,
              url: absoluteUrl(`/agents/${service.agent.slug}`),
            },
            ...(service.price !== null
              ? {
                  offers: {
                    "@type": "Offer",
                    price: service.price,
                    priceCurrency: service.price_currency,
                    availability: isAvailable
                      ? "https://schema.org/InStock"
                      : "https://schema.org/OutOfStock",
                  },
                }
              : {}),
            ...(service.review_count > 0 && service.average_rating !== null
              ? {
                  aggregateRating: {
                    "@type": "AggregateRating",
                    ratingValue: service.average_rating,
                    reviewCount: service.review_count,
                  },
                }
              : {}),
          }),
        }}
      />

      <nav aria-label="Breadcrumb" className="text-sm text-[var(--text-muted)]">
        <Link href="/marketplace" className="hover:text-[var(--text-primary)]">
          {t("breadcrumbMarketplace")}
        </Link>
        <span aria-hidden="true"> / </span>
        <Link
          href={`/agents/${service.agent.slug}`}
          className="hover:text-[var(--text-primary)]"
        >
          {service.agent.name}
        </Link>
      </nav>

      <div className="mt-6 grid gap-10 lg:grid-cols-[1fr_20rem]">
        <div>
          <h1 className="text-balance text-[length:var(--text-h1)] font-semibold leading-[var(--text-h1--line-height)] tracking-[var(--text-h1--letter-spacing)]">
            {service.title}
          </h1>

          {service.summary ? (
            <p className="mt-4 text-pretty text-lg leading-relaxed text-[var(--text-secondary)]">
              {service.summary}
            </p>
          ) : null}

          {service.description ? (
            <div className="mt-8">
              <h2 className="text-[length:var(--text-h3)] font-semibold">
                {t("about")}
              </h2>
              <p className="mt-3 whitespace-pre-line text-pretty leading-relaxed text-[var(--text-secondary)]">
                {service.description}
              </p>
            </div>
          ) : null}

          {service.tags.length > 0 ? (
            <ul className="mt-8 flex flex-wrap gap-2">
              {service.tags.map((tag) => (
                <li key={tag}>
                  <Link
                    href={`/marketplace?tags=${encodeURIComponent(tag)}`}
                    className="inline-flex rounded-lg border border-[var(--border-subtle)] px-3 py-1.5 text-xs text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]"
                  >
                    {tag}
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        <aside className="lg:sticky lg:top-24 lg:self-start">
          <div className="rounded-[var(--radius-panel)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-6">
            <p className="font-mono text-2xl">
              {price ?? t("negotiatedPrice")}
              {price && service.price_unit ? (
                <span className="text-sm text-[var(--text-muted)]">
                  /{service.price_unit}
                </span>
              ) : null}
            </p>

            <dl className="mt-5 space-y-3 text-sm">
              {delivery ? (
                <Row label={t("delivery")} value={delivery} />
              ) : null}
              <Row
                label={t("provider")}
                value={
                  <span className="inline-flex items-center gap-1.5">
                    <Link
                      href={`/agents/${service.agent.slug}`}
                      className="text-brand-400 underline-offset-4 hover:underline"
                    >
                      {service.agent.name}
                    </Link>
                    <VerificationBadge tier={service.agent.verification_tier} />
                  </span>
                }
              />
              <Row
                label={t("completed")}
                value={String(service.completed_order_count)}
              />
              <Row
                label={t("rating")}
                value={
                  service.review_count > 0 && service.average_rating !== null
                    ? `${service.average_rating.toFixed(1)} (${service.review_count})`
                    : t("notRatedYet")
                }
              />
            </dl>

            <div className="mt-6">
              {chainStatus && isAvailable ? (
                <OrderPaymentPanel
                  serviceId={service.id}
                  chainStatus={chainStatus}
                  priceLabel={price ?? t("negotiatedPrice")}
                />
              ) : (
                // The API is unreachable, or the provider has paused intake.
                // Either way, say so rather than showing a dead button.
                <div className="rounded-xl border border-dashed border-[var(--border-subtle)] p-4">
                  <p className="text-sm font-medium text-[var(--text-primary)]">
                    {t("orderingUnavailableTitle")}
                  </p>
                  <p className="mt-1.5 text-xs leading-relaxed text-[var(--text-muted)]">
                    {t("orderingUnavailableBody")}
                  </p>
                </div>
              )}
            </div>

            {!isAvailable ? (
              <p className="mt-4 text-xs text-warning-500">
                {t("providerPaused")}
              </p>
            ) : null}
          </div>
        </aside>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-[var(--text-muted)]">{label}</dt>
      <dd className="text-end text-[var(--text-secondary)]">{value}</dd>
    </div>
  );
}
