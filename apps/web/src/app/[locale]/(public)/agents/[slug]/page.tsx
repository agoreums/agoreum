import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { ServiceCard } from "@/components/marketplace/service-card";
import { VerificationBadge } from "@/components/marketplace/verification-badge";
import { BreadcrumbJsonLd, JsonLd } from "@/components/seo/json-ld";
import { ApiError, marketplaceApi, type AgentProfile } from "@/lib/api";
import { absoluteUrl } from "@/lib/site";

export const dynamic = "force-dynamic";

async function loadAgent(slug: string): Promise<AgentProfile | null> {
  try {
    return await marketplaceApi.agent(slug);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function generateMetadata(props: {
  params: Promise<{ locale: string; slug: string }>;
}): Promise<Metadata> {
  const { slug } = await props.params;
  const agent = await loadAgent(slug).catch(() => null);

  if (!agent) return { title: "Agent not found" };

  return {
    title: agent.name,
    description: agent.tagline ?? undefined,
    alternates: { canonical: absoluteUrl(`/agents/${agent.slug}`) },
    openGraph: {
      title: agent.name,
      description: agent.tagline ?? undefined,
      url: absoluteUrl(`/agents/${agent.slug}`),
      type: "profile",
    },
  };
}

export default async function AgentProfilePage(props: {
  params: Promise<{ locale: string; slug: string }>;
}) {
  const { locale, slug } = await props.params;
  setRequestLocale(locale);

  const t = await getTranslations("agentProfile");
  const tCap = await getTranslations("agentProfile.capabilities");
  const tMod = await getTranslations("capabilityModality");
  const agent = await loadAgent(slug);
  if (!agent) notFound();

  const caps = agent.capabilities;
  const hasCapabilities = Boolean(
    caps &&
      (caps.skills?.length ||
        caps.languages?.length ||
        caps.input_modalities?.length ||
        caps.output_modalities?.length ||
        caps.protocols?.length),
  );
  // Fall back to the raw value if a modality is not yet localized, so a new
  // vocabulary term never renders as a missing-translation key.
  const modalityLabel = (value: string) =>
    tMod.has(value) ? tMod(value) : value.replace(/_/g, " ");

  const services = await marketplaceApi.agentServices(slug).catch(() => []);
  const published = services.filter((s) => s.status === "published");

  return (
    <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
      <BreadcrumbJsonLd
        items={[
          { name: "Agoreum", url: absoluteUrl("/") },
          { name: t("breadcrumb"), url: absoluteUrl("/agents") },
          { name: agent.name, url: absoluteUrl(`/agents/${agent.slug}`) },
        ]}
      />
      {/* Structured data describes only what is true. No aggregateRating is
          emitted unless there are real reviews behind it. */}
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "Organization",
          name: agent.name,
          description: agent.tagline ?? undefined,
          url: absoluteUrl(`/agents/${agent.slug}`),
          ...(agent.verified_domain
            ? { sameAs: [`https://${agent.verified_domain}`] }
            : {}),
          ...(agent.review_count > 0 && agent.average_rating !== null
            ? {
                aggregateRating: {
                  "@type": "AggregateRating",
                  ratingValue: agent.average_rating,
                  reviewCount: agent.review_count,
                },
              }
            : {}),
        }}
      />

      <header className="border-b border-[var(--border-subtle)] pb-8">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="max-w-2xl">
            <div className="flex items-center gap-2.5">
              <h1 className="text-[length:var(--text-h1)] font-semibold leading-[var(--text-h1--line-height)] tracking-[var(--text-h1--letter-spacing)]">
                {agent.name}
              </h1>
              <VerificationBadge tier={agent.verification_tier} showLabel />
            </div>

            <p className="mt-1 font-mono text-sm text-[var(--text-muted)]">
              @{agent.slug}
            </p>

            {agent.tagline ? (
              <p className="mt-4 text-pretty leading-relaxed text-[var(--text-secondary)]">
                {agent.tagline}
              </p>
            ) : null}

            {agent.verified_domain ? (
              <p className="mt-3 text-sm text-[var(--text-secondary)]">
                {t("verifiedDomain")}{" "}
                <a
                  href={`https://${agent.verified_domain}`}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="text-brand-400 underline-offset-4 hover:underline"
                >
                  {agent.verified_domain}
                </a>
              </p>
            ) : null}
          </div>

          <dl className="grid grid-cols-3 gap-6 text-sm">
            <Stat label={t("stats.completed")} value={agent.completed_orders} />
            <Stat
              label={t("stats.services")}
              value={published.length}
            />
            <Stat
              label={t("stats.rating")}
              // Null, not zero. An unrated agent is unknown, not bad.
              value={
                agent.review_count > 0 && agent.average_rating !== null
                  ? `${agent.average_rating.toFixed(1)} (${agent.review_count})`
                  : t("stats.notRated")
              }
            />
          </dl>
        </div>
      </header>

      {agent.description ? (
        <section className="mt-8 max-w-3xl">
          <h2 className="text-[length:var(--text-h3)] font-semibold">
            {t("about")}
          </h2>
          <p className="mt-3 whitespace-pre-line text-pretty leading-relaxed text-[var(--text-secondary)]">
            {agent.description}
          </p>
        </section>
      ) : null}

      {hasCapabilities ? (
        <section className="mt-10 max-w-3xl">
          <h2 className="text-[length:var(--text-h3)] font-semibold">
            {tCap("title")}
          </h2>
          <div className="mt-4 space-y-4">
            {caps.skills?.length ? (
              <CapabilityGroup label={tCap("skills")} items={caps.skills} />
            ) : null}
            {caps.input_modalities?.length ? (
              <CapabilityGroup
                label={tCap("inputs")}
                items={caps.input_modalities.map(modalityLabel)}
              />
            ) : null}
            {caps.output_modalities?.length ? (
              <CapabilityGroup
                label={tCap("outputs")}
                items={caps.output_modalities.map(modalityLabel)}
              />
            ) : null}
            {caps.protocols?.length ? (
              <CapabilityGroup
                label={tCap("protocols")}
                items={caps.protocols.map((p) => PROTOCOL_LABELS[p] ?? p)}
              />
            ) : null}
            {caps.languages?.length ? (
              <CapabilityGroup label={tCap("languages")} items={caps.languages} />
            ) : null}
          </div>
        </section>
      ) : null}

      <section className="mt-12">
        <h2 className="text-[length:var(--text-h2)] font-semibold tracking-[var(--text-h2--letter-spacing)]">
          {t("services")}
        </h2>

        {published.length > 0 ? (
          <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {published.map((service) => (
              <li key={service.id}>
                <ServiceCard service={service} locale={locale} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-6 rounded-[var(--radius-card)] border border-dashed border-[var(--border-subtle)] p-8 text-center text-sm text-[var(--text-muted)]">
            {t("noServices")}
          </p>
        )}
      </section>
    </div>
  );
}

// Protocol identifiers are technical proper nouns, shown as-is across locales.
const PROTOCOL_LABELS: Record<string, string> = {
  rest: "REST",
  webhook: "Webhook",
  mcp: "MCP",
  a2a: "A2A",
  graphql: "GraphQL",
  grpc: "gRPC",
};

function CapabilityGroup({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-baseline sm:gap-4">
      <span className="w-28 flex-none text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
        {label}
      </span>
      <ul className="flex flex-wrap gap-2">
        {items.map((item) => (
          <li
            key={item}
            className="rounded-full border border-[var(--border-subtle)] bg-[var(--surface-raised)] px-3 py-1 text-sm text-[var(--text-secondary)]"
          >
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-xs text-[var(--text-muted)]">{label}</dt>
      <dd className="mt-1 font-mono text-base text-[var(--text-primary)]">
        {value}
      </dd>
    </div>
  );
}
