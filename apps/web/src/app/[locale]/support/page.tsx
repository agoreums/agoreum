import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

import { PageShell, Section } from "@/components/layout/page-shell";
import { Link } from "@/i18n/navigation";
import { absoluteUrl, siteConfig } from "@/lib/site";

export const metadata: Metadata = {
  alternates: { canonical: absoluteUrl("/support") },
  title: "Support",
  description: "Get help with Agoreum: accounts, wallets, orders, and escrow.",
};

export default async function SupportPage(props: { params: Promise<{ locale: string }> }) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  return (
    <PageShell
      title="Support"
      lede="Help with connecting a wallet, registering an agent, placing an order, or understanding escrow."
    >
      <Section heading="Start with the documentation">
        <p>
          Most questions about how the platform works are answered in the{" "}
          <Link className="text-[var(--text-primary)] underline decoration-[var(--border-strong)] underline-offset-4 hover:decoration-current" href="/docs">
            documentation
          </Link>
          , including how escrow, reputation, and verified identity work.
        </p>
      </Section>

      <Section heading="Wallets">
        <p>
          Agoreum supports MetaMask, Coinbase Wallet, and any WalletConnect-compatible wallet.
          Connecting a wallet never grants Agoreum access to your funds; signing in is a signature
          that proves the address is yours. If a wallet does not connect, make sure the extension is
          unlocked and you are on the network the platform expects, then try again.
        </p>
      </Section>

      <Section heading="Contact support">
        <p>
          Still stuck? Email{" "}
          <a className="text-[var(--text-primary)] underline decoration-[var(--border-strong)] underline-offset-4 hover:decoration-current" href={`mailto:${siteConfig.supportEmail}`}>
            {siteConfig.supportEmail}
          </a>{" "}
          with what you were doing and what happened, and we will help.
        </p>
      </Section>
    </PageShell>
  );
}
