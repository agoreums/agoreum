import { absoluteUrl, siteConfig } from "@/lib/site";

/**
 * Structured data.
 *
 * Only facts that are actually true today are described here. Schema.org types that
 * would imply activity the platform has not yet had, aggregate ratings, offer
 * counts, transaction volume, are deliberately absent, and will be added when
 * there is real data behind them.
 */
/**
 * Serialise a JSON-LD payload for inline injection.
 *
 * `JSON.stringify` escapes quotes and backslashes, but not `<`. A value
 * containing `</script>` therefore closes the element early and everything after
 * it is parsed as markup, and because the CSP carries `script-src 'unsafe-inline'`
 * that markup runs. This is not hypothetical here: `BreadcrumbJsonLd` and
 * `ServiceProductJsonLd` are handed agent names and service titles, which any
 * visitor can set on a self-service agent and publish without review, and the
 * backend constrains those fields by length only.
 *
 * Escaping happens at the sink rather than on input because the sink is the only
 * place that can be complete: the same strings render safely as JSX text
 * everywhere else, so filtering them on the way in would damage legitimate values
 * while still missing any future call site. U+2028 and U+2029 are included
 * because they are valid inside a JSON string but terminate a JavaScript line.
 */
export function serializeJsonLd(data: Record<string, unknown>): string {
  return JSON.stringify(data)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

export function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: serializeJsonLd(data) }}
    />
  );
}

export function OrganizationJsonLd() {
  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@type": "Organization",
        name: siteConfig.name,
        url: siteConfig.url,
        logo: absoluteUrl("/icons/android-chrome-512x512.png"),
        email: siteConfig.supportEmail,
        sameAs: [
          siteConfig.social.x,
          siteConfig.social.discord,
          siteConfig.social.reddit,
          siteConfig.social.telegram,
          siteConfig.social.instagram,
          siteConfig.social.github,
        ],
      }}
    />
  );
}

export function WebSiteJsonLd({ description }: { description: string }) {
  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@type": "WebSite",
        name: siteConfig.name,
        url: siteConfig.url,
        description,
        publisher: { "@type": "Organization", name: siteConfig.name },
        // Lets search engines expose a sitelinks search box into the marketplace.
        potentialAction: {
          "@type": "SearchAction",
          target: {
            "@type": "EntryPoint",
            urlTemplate: absoluteUrl("/marketplace?q={search_term_string}"),
          },
          "query-input": "required name=search_term_string",
        },
      }}
    />
  );
}

/**
 * The platform itself as a web application. No `offers` or `aggregateRating` is
 * asserted, because usage is not a fixed price and there is no rating to claim.
 */
export function SoftwareApplicationJsonLd({ description }: { description: string }) {
  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        name: siteConfig.name,
        url: siteConfig.url,
        description,
        applicationCategory: "BusinessApplication",
        operatingSystem: "Web",
        publisher: { "@type": "Organization", name: siteConfig.name },
      }}
    />
  );
}

/** A breadcrumb trail for a nested page. Positions are 1-based. */
export function BreadcrumbJsonLd({ items }: { items: { name: string; url: string }[] }) {
  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        itemListElement: items.map((item, index) => ({
          "@type": "ListItem",
          position: index + 1,
          name: item.name,
          item: item.url,
        })),
      }}
    />
  );
}

/**
 * A marketplace service as a Product offering. An `offers` block is emitted only
 * when the service has a real fixed price; negotiated pricing asserts no number.
 */
export function ServiceProductJsonLd({
  name,
  description,
  url,
  sellerName,
  price,
  priceCurrency,
}: {
  name: string;
  description?: string | null;
  url: string;
  sellerName: string;
  price?: string | null;
  priceCurrency?: string | null;
}) {
  const data: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "Product",
    name,
    url,
    brand: { "@type": "Organization", name: sellerName },
  };
  if (description) data.description = description;
  if (price && priceCurrency) {
    data.offers = {
      "@type": "Offer",
      price,
      priceCurrency,
      availability: "https://schema.org/InStock",
      url,
    };
  }
  return <JsonLd data={data} />;
}
