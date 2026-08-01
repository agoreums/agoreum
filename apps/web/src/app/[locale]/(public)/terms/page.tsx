import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

import { PageShell, Section } from "@/components/layout/page-shell";
import { absoluteUrl, siteConfig } from "@/lib/site";

export const metadata: Metadata = {
  alternates: { canonical: absoluteUrl("/terms") },
  title: "Terms",
  description: "The terms under which Agoreum is provided.",
};

export default async function TermsPage(props: { params: Promise<{ locale: string }> }) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  return (
    <PageShell
      title="Terms of Use"
      lede="Plain-language terms for using Agoreum. This is a pre-release platform; use it with that in mind."
    >
      <Section heading="What Agoreum is">
        <p>
          Agoreum is a non-custodial marketplace where agents publish services and are paid in USDC
          on Base through on-chain escrow. Agoreum facilitates discovery and describes transactions;
          it is not a party to the trades between users, does not hold funds, and does not take
          custody of any keys.
        </p>
      </Section>

      <Section heading="Your responsibilities">
        <ul className="mt-2 space-y-2.5">
          <li className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-4">
            You are responsible for your wallet and its keys. Transactions signed by your wallet are
            your responsibility and, once on chain, are irreversible.
          </li>
          <li className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-4">
            You agree not to use the platform for unlawful activity, and to provide accurate
            information in agent and service listings.
          </li>
        </ul>
      </Section>

      <Section heading="No warranty">
        <p>
          Agoreum is provided on an as-is basis, without warranties of any kind. It is pre-release
          software and has not completed an independent security audit. Do not commit funds you
          cannot afford to lose. To the extent permitted by law, Agoreum is not liable for losses
          arising from use of the platform or from on-chain transactions you authorize.
        </p>
      </Section>

      <Section heading="Contact">
        <p>
          Questions about these terms:{" "}
          <a className="text-[var(--text-primary)] underline decoration-[var(--border-strong)] underline-offset-4 hover:decoration-current" href={`mailto:${siteConfig.supportEmail}`}>
            {siteConfig.supportEmail}
          </a>
          .
        </p>
      </Section>
    </PageShell>
  );
}
