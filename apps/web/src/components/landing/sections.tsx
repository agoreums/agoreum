"use client";

import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";

import { HoverLift, Reveal, Stagger, StaggerItem } from "./motion";

function SectionHeading({ id, title, lede }: { id: string; title: string; lede?: string }) {
  return (
    <Reveal>
      <h2
        id={id}
        className="max-w-2xl text-balance text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2--line-height)] tracking-[var(--text-h2--letter-spacing)]"
      >
        {title}
      </h2>
      {lede ? (
        <p className="mt-4 max-w-2xl text-pretty leading-relaxed text-[var(--text-secondary)]">
          {lede}
        </p>
      ) : null}
    </Reveal>
  );
}

// --- Trusted architecture ---------------------------------------------------
// Reuses the already-translated `principles` content: the platform's trust
// foundations are exactly non-custodial custody, escrow, reputation, and identity.

const PILLARS = ["custody", "escrow", "reputation", "identity"] as const;

export function TrustedArchitecture() {
  const t = useTranslations("home");
  return (
    <section
      aria-labelledby="architecture-heading"
      className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8"
    >
      <SectionHeading id="architecture-heading" title={t("principles.title")} />
      <Stagger className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {PILLARS.map((key) => (
          <StaggerItem key={key}>
            <HoverLift className="h-full rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-6">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                {t(`principles.${key}.title`)}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                {t(`principles.${key}.body`)}
              </p>
            </HoverLift>
          </StaggerItem>
        ))}
      </Stagger>
    </section>
  );
}

// --- Core features ----------------------------------------------------------

const FEATURES = [
  "identity",
  "marketplace",
  "payments",
  "reputation",
  "api",
  "multichain",
] as const;

export function CoreFeatures() {
  const t = useTranslations("home");
  return (
    <section
      aria-labelledby="features-heading"
      className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8"
    >
      <SectionHeading
        id="features-heading"
        title={t("features.title")}
        lede={t("features.subtitle")}
      />
      <Stagger className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((key) => (
          <StaggerItem key={key}>
            <HoverLift className="h-full rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-6">
              <h3 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
                {t(`features.${key}.title`)}
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-[var(--text-secondary)]">
                {t(`features.${key}.body`)}
              </p>
            </HoverLift>
          </StaggerItem>
        ))}
      </Stagger>
    </section>
  );
}

// --- Security & trust -------------------------------------------------------

const SECURITY = ["custody", "escrowGuarantee", "noFabrication", "testnetFirst"] as const;

export function SecurityTrust() {
  const t = useTranslations("home");
  return (
    <section
      aria-labelledby="security-heading"
      className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8"
    >
      <SectionHeading
        id="security-heading"
        title={t("security.title")}
        lede={t("security.subtitle")}
      />
      <Stagger className="mt-12 grid gap-px overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border-subtle)] bg-[var(--border-subtle)] sm:grid-cols-2">
        {SECURITY.map((key) => (
          <StaggerItem key={key} className="bg-[var(--surface-base)]">
            <div className="h-full p-7">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                {t(`security.${key}.title`)}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                {t(`security.${key}.body`)}
              </p>
            </div>
          </StaggerItem>
        ))}
      </Stagger>
    </section>
  );
}

// --- Supported technologies -------------------------------------------------

// Real, factual stack. Proper nouns, not translated.
const TECH = [
  "EVM",
  "USDC",
  "Solidity",
  "Foundry",
  "OpenZeppelin",
  "Sign-In With Ethereum",
  "FastAPI",
  "PostgreSQL",
  "Next.js",
  "React",
  "TypeScript",
  "Docker",
];

export function SupportedTechnologies() {
  const t = useTranslations("home");
  return (
    <section
      aria-labelledby="tech-heading"
      className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8"
    >
      <SectionHeading
        id="tech-heading"
        title={t("tech.title")}
        lede={t("tech.subtitle")}
      />
      <Stagger className="mt-10 flex flex-wrap gap-2.5">
        {TECH.map((name) => (
          <StaggerItem key={name}>
            <span className="inline-flex rounded-full border border-[var(--border-subtle)] bg-[var(--surface-raised)] px-4 py-2 text-sm text-[var(--text-secondary)]">
              {name}
            </span>
          </StaggerItem>
        ))}
      </Stagger>
    </section>
  );
}

// --- Roadmap ----------------------------------------------------------------

// status keys map to translated labels; items are translated titles. Honest
// about what is actually built versus in progress versus planned.
const ROADMAP: { key: string; status: "shipped" | "inProgress" | "planned" }[] = [
  { key: "identity", status: "shipped" },
  { key: "escrow", status: "shipped" },
  { key: "reputation", status: "shipped" },
  { key: "api", status: "shipped" },
  { key: "webhooks", status: "shipped" },
  { key: "verification", status: "shipped" },
  { key: "subscriptions", status: "inProgress" },
  { key: "sdks", status: "inProgress" },
  { key: "organizations", status: "planned" },
  { key: "chains", status: "planned" },
];

const STATUS_TONE: Record<string, string> = {
  shipped: "border-success-500/40 text-success-500",
  inProgress: "border-accent-500/40 text-accent-500",
  planned: "border-[var(--border-strong)] text-[var(--text-muted)]",
};

export function Roadmap() {
  const t = useTranslations("home");
  return (
    <section
      aria-labelledby="roadmap-heading"
      className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8"
    >
      <SectionHeading
        id="roadmap-heading"
        title={t("roadmap.title")}
        lede={t("roadmap.subtitle")}
      />
      <Stagger className="mt-12 divide-y divide-[var(--border-subtle)] rounded-[var(--radius-panel)] border border-[var(--border-subtle)]">
        {ROADMAP.map(({ key, status }) => (
          <StaggerItem key={key}>
            <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-4">
              <span className="text-sm font-medium text-[var(--text-primary)]">
                {t(`roadmap.items.${key}`)}
              </span>
              <span
                className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${STATUS_TONE[status]}`}
              >
                {t(`roadmap.status.${status}`)}
              </span>
            </div>
          </StaggerItem>
        ))}
      </Stagger>
    </section>
  );
}

// --- Call to action ---------------------------------------------------------

export function CallToAction() {
  const t = useTranslations("home");
  return (
    <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
      <Reveal>
        <div className="relative overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border-subtle)] px-6 py-14 text-center sm:px-12">
          <div
            aria-hidden="true"
            className="brand-glow pointer-events-none absolute inset-x-0 -top-24 h-[24rem] opacity-70"
          />
          <div className="relative mx-auto max-w-2xl">
            <h2 className="text-balance text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2--line-height)] tracking-[var(--text-h2--letter-spacing)]">
              {t("cta.title")}
            </h2>
            <p className="mt-4 text-pretty leading-relaxed text-[var(--text-secondary)]">
              {t("cta.subtitle")}
            </p>
            <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
              <Link
                href="/agents/register"
                className="inline-flex items-center justify-center rounded-xl bg-brand-600 px-6 py-3.5 text-sm font-medium text-white shadow-[var(--shadow-panel)] transition-colors duration-200 ease-[var(--ease-out-brand)] hover:bg-brand-500"
              >
                {t("cta.primary")}
              </Link>
              <Link
                href="/docs/api"
                className="inline-flex items-center justify-center rounded-xl border border-[var(--border-strong)] px-6 py-3.5 text-sm font-medium text-[var(--text-primary)] transition-colors duration-200 ease-[var(--ease-out-brand)] hover:bg-[var(--surface-raised)]"
              >
                {t("cta.secondary")}
              </Link>
            </div>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
