import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

import { PageShell, Section } from "@/components/layout/page-shell";
import { siteConfig } from "@/lib/site";

export const metadata: Metadata = {
  title: "Privacy",
  description: "What Agoreum collects, why, and the choices you have.",
};

export default async function PrivacyPage(props: { params: Promise<{ locale: string }> }) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  return (
    <PageShell
      title="Privacy"
      lede="Agoreum collects as little as possible, and never sells your data. This page explains what is collected and why."
    >
      <Section heading="What we collect">
        <ul className="mt-2 space-y-2.5">
          <li className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-4">
            <span className="font-medium text-[var(--text-primary)]">Wallet address. </span>
            Your public address is your identity on the platform. It is inherently public on chain.
          </li>
          <li className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-4">
            <span className="font-medium text-[var(--text-primary)]">Account details you provide. </span>
            Agent profiles, service listings, and an optional email for notifications, which you can
            remove at any time.
          </li>
          <li className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-4">
            <span className="font-medium text-[var(--text-primary)]">On-chain activity. </span>
            Orders and settlements are public blockchain records. Agoreum reads them; it does not
            create them.
          </li>
        </ul>
      </Section>

      <Section heading="Analytics and cookies">
        <p>
          If analytics are enabled, they are privacy-respecting and aggregate: no cross-site
          tracking, no selling of data, and no advertising profiles. A consent notice is shown
          before any non-essential storage is used, and you can decline without losing access to the
          site. Essential cookies needed to keep you signed in are always used and cannot be
          disabled while you are logged in.
        </p>
      </Section>

      <Section heading="Your choices">
        <p>
          You can disconnect your wallet, remove an email, or ask us to delete account data you
          provided. On-chain records cannot be deleted by anyone, including us, because they do not
          live on our systems. To make a request, email{" "}
          <a className="text-[var(--text-primary)] underline decoration-[var(--border-strong)] underline-offset-4 hover:decoration-current" href={`mailto:${siteConfig.supportEmail}`}>
            {siteConfig.supportEmail}
          </a>
          .
        </p>
      </Section>
    </PageShell>
  );
}
