import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

import { PageShell, Section } from "@/components/layout/page-shell";
import { ReceiptVerifier } from "@/components/receipts/receipt-verifier";
import type { Locale } from "@/i18n/routing";
import { localizedAlternates, socialCard } from "@/lib/site";

const TITLE = "Verify a receipt";
const DESCRIPTION =
  "Check an Agoreum settlement receipt yourself, in your own browser, without trusting Agoreum.";

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  return {
    alternates: localizedAlternates(locale as Locale, "/verify"),
    title: TITLE,
    description: DESCRIPTION,
    ...socialCard({
      locale: locale as Locale,
      path: "/verify",
      title: TITLE,
      description: DESCRIPTION,
    }),
  };
}

export default async function VerifyPage(props: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  return (
    <PageShell
      title={TITLE}
      lede="Anyone can check an Agoreum receipt without an account, without our help, and without taking our word for any part of it."
    >
      <Section heading="What a receipt is">
        <p>
          When an order settles through escrow, Agoreum issues a signed statement
          describing what happened: which escrow, which contract, which chain,
          how much moved, to whom, and in which transaction. That statement is
          signed with a key published at{" "}
          <a
            className="underline decoration-[var(--border-strong)] underline-offset-4"
            href="/.well-known/agoreum-receipts.json"
          >
            /.well-known/agoreum-receipts.json
          </a>
          , which anyone can fetch.
        </p>
        <p>
          The signature is not the evidence. It proves only that Agoreum made
          this exact statement and that nobody has altered it since. What makes
          the statement true is the transaction on Base, which exists whether or
          not Agoreum is around to vouch for it, and which you can look up
          yourself. If the two ever disagree, the chain is right and we are
          wrong.
        </p>
        <p>
          That distinction is the whole design. A marketplace score that rests on
          the marketplace being honest is worth what every other one is worth.
          This one rests on a payment you can go and look at.
        </p>
      </Section>

      <Section heading="Check one now">
        <p>
          Paste a receipt below. Nothing is uploaded. The check runs in your
          browser, and the only request made is for the public key document
          linked above, which you are welcome to fetch yourself instead.
        </p>
        <ReceiptVerifier />
      </Section>

      <Section heading="Checking it without this page">
        <p>
          This page is a convenience, not the mechanism, and relying on it would
          reintroduce the trust it exists to remove. The receipt is checkable
          with any Ed25519 library in any language: canonicalise the receipt
          object with keys sorted at every level, no whitespace between tokens,
          UTF-8, and no escaping of non-ASCII characters, then verify the
          signature over those bytes against the published key. Then follow the
          transaction hash on chain.
        </p>
        <p>
          Agoreum is on Base Sepolia testnet today, so the balances involved are
          test funds with no real value. The verification path is the one that
          will carry real settlements later, which is why it is worth being able
          to check now.
        </p>
      </Section>
    </PageShell>
  );
}
