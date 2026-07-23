import { absoluteUrl, siteConfig } from "@/lib/site";

/**
 * Structured data.
 *
 * Only facts that are actually true today are described here. Schema.org types that
 * would imply activity the platform has not yet had — aggregate ratings, offer
 * counts, transaction volume — are deliberately absent, and will be added when
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
      }}
    />
  );
}
