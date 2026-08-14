import type { Metadata } from "next";

import type { Locale } from "@/i18n/routing";
import { setRequestLocale } from "next-intl/server";

import { PageShell, Section } from "@/components/layout/page-shell";
import {siteConfig, localizedAlternates, socialCard } from "@/lib/site";

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  return {
    alternates: localizedAlternates(locale as Locale, "/privacy"),
    title: "Privacy",
    description: "What Agoreum collects, why, and the choices you have.",
    ...socialCard({
      locale: locale as Locale,
      path: "/privacy",
      title: "Privacy",
      description: "What Agoreum collects, why, and the choices you have.",
    }),
  };
}

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
          We use{" "}
          <a
            href="https://umami.is"
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--text-primary)] underline decoration-[var(--border-strong)] underline-offset-4 hover:decoration-current"
          >
            Umami
          </a>
          , a privacy-respecting analytics tool that we host ourselves on the same infrastructure as
          this site. It is cookieless: it sets no cookies, assigns no cross-site identifier, builds
          no advertising profile, and collects no personal data. Aggregate figures such as page
          views and referrers never leave our servers and are never sold.
        </p>
        <p>
          Even though it is cookieless, analytics load only after you accept the consent notice
          shown on your first visit. Decline and nothing is sent; your choice is remembered in your
          browser&apos;s local storage, not in a tracking cookie. Essential storage needed to keep
          you signed in is used only while you are logged in.
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
