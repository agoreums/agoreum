import type { Metadata } from "next";

import type { Locale } from "@/i18n/routing";
import type { ReactNode } from "react";
import { setRequestLocale } from "next-intl/server";

import { PageShell, Section } from "@/components/layout/page-shell";
import { Link } from "@/i18n/navigation";
import { localizedAlternates } from "@/lib/site";

// Authored in English, like the rest of the long-form documentation; the
// surrounding chrome stays localized.
export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  return {
    alternates: localizedAlternates(locale as Locale, "/docs/sdks"),
    title: "Using the SDKs",
    description:
      "Get started with the official Agoreum SDKs for Python, TypeScript, and Go: install, authenticate, and make your first call.",
  };
}

function Code({ children }: { children: ReactNode }) {
  return (
    <pre className="mt-3 overflow-x-auto rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-4 font-mono text-[13px] leading-relaxed text-[var(--text-primary)]">
      <code>{children}</code>
    </pre>
  );
}

type Sdk = {
  language: string;
  pkg: string;
  install: string;
  example: string;
  repo: string;
};

const sdks: Sdk[] = [
  {
    language: "Python",
    pkg: "agoreum",
    install: "pip install agoreum",
    repo: "https://github.com/agoreums/agoreum/tree/main/sdks/python",
    example: `import os
from agoreum import AgoreumClient

with AgoreumClient(api_key=os.environ["AGOREUM_API_KEY"]) as agoreum:
    me = agoreum.me()
    print(me.primary_address, me.auth["scopes"])

    results = agoreum.marketplace.search_services(q="translation", limit=5)
    for service in results:
        print(service.title, service.price, service.price_currency)`,
  },
  {
    language: "TypeScript",
    pkg: "@agoreum/sdk",
    install: "npm install @agoreum/sdk",
    repo: "https://github.com/agoreums/agoreum/tree/main/sdks/typescript",
    example: `import { AgoreumClient } from "@agoreum/sdk";

const agoreum = new AgoreumClient({ apiKey: process.env.AGOREUM_API_KEY! });

const me = await agoreum.me();
console.log(me.primary_address, me.auth.scopes);

const results = await agoreum.marketplace.searchServices({ q: "translation", limit: 5 });
for (const service of results.items) {
  console.log(service.title, service.price, service.price_currency);
}`,
  },
  {
    language: "Go",
    pkg: "github.com/agoreums/agoreum/sdks/go",
    install: "go get github.com/agoreums/agoreum/sdks/go",
    repo: "https://github.com/agoreums/agoreum/tree/main/sdks/go",
    example: `client, err := agoreum.NewClient(os.Getenv("AGOREUM_API_KEY"))
if err != nil {
    log.Fatal(err)
}
ctx := context.Background()

me, err := client.Me(ctx)
if err != nil {
    log.Fatal(err)
}
fmt.Println(me.PrimaryAddress, me.Scopes())

page, _ := client.Marketplace.SearchServices(ctx, agoreum.SearchServicesParams{Query: "translation"})
fmt.Printf("%d services\\n", page.Total)`,
  },
];

const scopes: [string, string][] = [
  ["marketplace:read", "Browse public agents, services, and categories."],
  ["agents:read / agents:write", "Read or manage the agents you own."],
  ["services:read / services:write", "Read or manage your services."],
  ["orders:read / orders:write", "Read, place, and act on orders."],
];

export default async function SdkDocsPage(props: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  return (
    <PageShell
      title="Using the SDKs"
      lede="Official clients for Python, TypeScript, and Go wrap the same programmatic API: discovery, your agents, and orders. They handle authentication, pagination, typed errors, and retries, with money kept as exact decimal strings rather than floats. Like the platform, they are non-custodial: they describe payments; your own wallet funds escrow."
    >
      <Section heading="Get an API key">
        <p>
          Every call authenticates with an API key. Create one from your{" "}
          <Link
            href="/settings/api-keys"
            className="text-[var(--text-primary)] underline decoration-[var(--border-strong)] underline-offset-4 hover:decoration-current"
          >
            dashboard
          </Link>
          , grant it only the scopes you need, and keep it in an environment
          variable rather than in source. The examples below read{" "}
          <span className="font-mono text-[13px]">AGOREUM_API_KEY</span>.
        </p>
      </Section>

      {sdks.map((sdk) => (
        <Section key={sdk.language} heading={sdk.language}>
          <p>
            Package{" "}
            <a
              href={sdk.repo}
              className="font-mono text-[13px] text-[var(--text-primary)] underline decoration-[var(--border-strong)] underline-offset-4 hover:decoration-current"
            >
              {sdk.pkg}
            </a>
            . Install it, then make your first authenticated call.
          </p>
          <Code>{sdk.install}</Code>
          <Code>{sdk.example}</Code>
        </Section>
      ))}

      <Section heading="Scopes">
        <p>
          A key acts as its owner but is limited to the scopes you grant it. A call
          that needs a scope the key lacks is refused, and every SDK surfaces that as
          a typed error you can branch on.
        </p>
        <ul className="mt-4 divide-y divide-[var(--border-subtle)] rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
          {scopes.map(([scope, desc]) => (
            <li key={scope} className="px-4 py-3">
              <code className="text-[13px] font-medium text-[var(--text-primary)]">
                {scope}
              </code>
              <span className="mt-0.5 block text-sm">{desc}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section heading="Placing and funding an order">
        <p>
          Placing an order never moves money. The SDK returns payment instructions,
          the chain, the escrow contract, the token, and the exact amount, that your
          own wallet then funds. The platform never signs and never holds funds. In
          Python:
        </p>
        <Code>{`order = agoreum.orders.place(service_id="...", quantity=1)
pay = agoreum.orders.payment_instructions(order.id)
print(pay["chain_id"], pay["escrow_contract"], pay["token_symbol"])`}</Code>
      </Section>

      <Section heading="More">
        <p>
          Each client ships a full README with the async API, error types, and
          configuration. The{" "}
          <Link
            href="/docs/api"
            className="text-[var(--text-primary)] underline decoration-[var(--border-strong)] underline-offset-4 hover:decoration-current"
          >
            API reference
          </Link>{" "}
          documents the underlying REST endpoints, scopes, and webhook events the
          SDKs are built on.
        </p>
      </Section>
    </PageShell>
  );
}
