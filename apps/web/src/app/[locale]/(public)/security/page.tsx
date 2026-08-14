import type { Metadata } from "next";

import type { Locale } from "@/i18n/routing";
import { setRequestLocale } from "next-intl/server";

import { PageShell, Section } from "@/components/layout/page-shell";
import {siteConfig, localizedAlternates } from "@/lib/site";

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  return {
    alternates: localizedAlternates(locale as Locale, "/security"),
    title: "Security",
    description: "How Agoreum protects funds, identities, and data, and how to report a vulnerability.",
  };
}

export default async function SecurityPage(props: { params: Promise<{ locale: string }> }) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  return (
    <PageShell
      title="Security"
      lede="Agoreum moves money between strangers, so it is built to hold up against a motivated attacker, not just a curious one."
    >
      <Section heading="Custody">
        <p>
          The platform holds no keys and no funds. No private key exists in any application
          configuration, and no code path can sign or broadcast a transaction. Your wallet signs;
          Agoreum only describes the transaction. If you ever find a path where the platform could
          move value on its own, that is a bug, and we want to hear about it.
        </p>
      </Section>

      <Section heading="On-chain">
        <p>
          Escrow is enforced by a smart contract that cannot pay out more than it took in, writes
          state before value moves, and guarantees every funded escrow a terminal outcome. The
          contract has been proven end to end on the Base Sepolia testnet and is pending an
          independent audit before mainnet.
        </p>
      </Section>

      <Section heading="Reporting a vulnerability">
        <p>
          Email <a className="text-[var(--text-primary)] underline decoration-[var(--border-strong)] underline-offset-4 hover:decoration-current" href={`mailto:${siteConfig.supportEmail}`}>{siteConfig.supportEmail}</a>.
          Please do not open a public issue for a security problem. Include what you found, how to
          reproduce it, and the impact you believe it has. We will confirm receipt and keep you
          updated, and we ask for reasonable time to fix an issue before public disclosure.
        </p>
      </Section>
    </PageShell>
  );
}
