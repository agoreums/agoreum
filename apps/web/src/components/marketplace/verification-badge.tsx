import { getTranslations } from "next-intl/server";

type Tier = "unverified" | "domain_verified" | "organization_verified";

/**
 * Indicates what has actually been proven about a provider.
 *
 * Renders nothing for an unverified agent. A neutral "unverified" chip would
 * be visual noise on the majority of listings, and — more importantly — the
 * absence of a badge is already the honest signal.
 */
export async function VerificationBadge({
  tier,
  showLabel = false,
}: {
  tier: Tier;
  showLabel?: boolean;
}) {
  if (tier === "unverified") return null;

  const t = await getTranslations("marketplace.verification");
  const isOrganization = tier === "organization_verified";
  const label = isOrganization ? t("organization") : t("domain");

  return (
    <span
      title={label}
      className={`inline-flex items-center gap-1 ${
        showLabel
          ? "rounded-full border border-[var(--border-subtle)] px-2 py-0.5 text-[0.6875rem]"
          : ""
      } ${isOrganization ? "text-brand-400" : "text-[var(--text-secondary)]"}`}
    >
      <svg
        viewBox="0 0 16 16"
        aria-hidden="true"
        className="h-3.5 w-3.5 shrink-0"
        fill="currentColor"
      >
        <path d="M8 1 2.5 3.2v4.1c0 3.4 2.3 6.5 5.5 7.5 3.2-1 5.5-4.1 5.5-7.5V3.2L8 1Zm2.9 5.1-3.4 3.5a.6.6 0 0 1-.9 0L5.1 8.2a.6.6 0 1 1 .9-.9l1 1.1 3-3a.6.6 0 1 1 .9.8Z" />
      </svg>
      {showLabel ? label : <span className="sr-only">{label}</span>}
    </span>
  );
}
