import { absoluteUrl, siteConfig } from "@/lib/site";

/**
 * Structured data.
 *
 * Only facts that are actually true today are described here. Schema.org types that
 * would imply activity the platform has not yet had, aggregate ratings, offer
 * counts, transaction volume, are deliberately absent, and will be added when
 * there is real data behind them.
 */
function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      // The payload is built from our own constants, never from user input.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
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
