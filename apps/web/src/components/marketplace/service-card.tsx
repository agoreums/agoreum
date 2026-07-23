import { getTranslations } from "next-intl/server";

import { VerificationBadge } from "@/components/marketplace/verification-badge";
import { Link } from "@/i18n/navigation";
import type { ServiceListItem } from "@/lib/api";

/**
 * Formats a price for display.
 *
 * Returns null when there is no price, so the caller renders "negotiated"
 * rather than a misleading "0".
 */
export function formatPrice(
  service: Pick<
    ServiceListItem,
    "price" | "price_currency" | "price_unit" | "pricing_model"
  >,
  locale: string,
): string | null {
  if (service.price === null) return null;

  const amount = Number(service.price);
  // USDC carries 6 decimals, but showing six on a listing is noise. Trailing
  // zeros are dropped and precision is preserved where it matters.
  const formatted = new Intl.NumberFormat(locale, {
    minimumFractionDigits: 0,
    maximumFractionDigits: amount < 1 ? 6 : 2,
  }).format(amount);

  return `${formatted} ${service.price_currency}`;
}

export function formatDelivery(hours: number | null): string | null {
  if (hours === null) return null;
  if (hours < 24) return `${hours}h`;
  const days = Math.round(hours / 24);
  return days === 1 ? "1 day" : `${days} days`;
}

export async function ServiceCard({
  service,
  locale,
}: {
  service: ServiceListItem;
  locale: string;
}) {
  const t = await getTranslations("marketplace");
  const price = formatPrice(service, locale);
  const delivery = formatDelivery(service.delivery_time_hours);

  return (
    <article className="group relative flex flex-col rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-5 transition-colors duration-200 ease-[var(--ease-out-brand)] hover:border-[var(--border-strong)]">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-[0.9375rem] font-semibold leading-snug tracking-[-0.01em]">
          <Link
            href={`/agents/${service.agent.slug}/services/${service.slug}`}
            // Stretched link keeps the whole card clickable without nesting
            // interactive elements inside an anchor.
            className="after:absolute after:inset-0 after:content-['']"
          >
            {service.title}
          </Link>
        </h3>
        {price ? (
          <p className="shrink-0 font-mono text-sm text-[var(--text-primary)]">
            {price}
            {service.price_unit ? (
              <span className="text-[var(--text-muted)]">
                /{service.price_unit}
              </span>
            ) : null}
          </p>
        ) : (
          <p className="shrink-0 text-xs text-[var(--text-muted)]">
            {t("negotiated")}
          </p>
        )}
      </div>

      {service.summary ? (
        <p className="mt-2 line-clamp-2 text-sm leading-relaxed text-[var(--text-secondary)]">
          {service.summary}
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-[var(--text-muted)]">
        <span className="inline-flex items-center gap-1.5">
          {service.agent.name}
          <VerificationBadge tier={service.agent.verification_tier} />
        </span>
        {delivery ? <span>· {t("deliveryIn", { time: delivery })}</span> : null}
      </div>

      <div className="mt-3 flex items-center gap-3 text-xs text-[var(--text-muted)]">
        {/* Only genuine, completed activity is shown. An unrated service says
            so plainly rather than displaying an empty star row. */}
        {service.review_count > 0 && service.average_rating !== null ? (
          <span className="text-[var(--text-secondary)]">
            ★ {service.average_rating.toFixed(1)}
            <span className="text-[var(--text-muted)]">
              {" "}
              ({service.review_count})
            </span>
          </span>
        ) : (
          <span>{t("noReviewsYet")}</span>
        )}
        {service.completed_order_count > 0 ? (
          <span>
            · {t("ordersCompleted", { count: service.completed_order_count })}
          </span>
        ) : null}
      </div>

      {service.tags.length > 0 ? (
        <ul className="mt-4 flex flex-wrap gap-1.5">
          {service.tags.slice(0, 4).map((tag) => (
            <li
              key={tag}
              className="rounded-md border border-[var(--border-subtle)] px-2 py-0.5 text-[0.6875rem] text-[var(--text-muted)]"
            >
              {tag}
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}
