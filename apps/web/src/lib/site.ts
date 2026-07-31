/**
 * Canonical site constants.
 *
 * Anything that appears in metadata, structured data, or the footer is defined
 * once here so the site, the manifest, and the social cards can never disagree.
 */

export const siteConfig = {
  name: "Agoreum",
  shortName: "Agoreum",
  domain: "agoreum.xyz",
  url: process.env.NEXT_PUBLIC_APP_URL ?? "https://agoreum.xyz",
  supportEmail: "support@agoreum.xyz",
  themeColor: "#0A0A12",
  social: {
    x: "https://x.com/agoreum",
    discord: "https://discord.gg/8AcrcjYfuS",
    reddit: "https://www.reddit.com/r/Agoreum",
    telegram: "https://t.me/agoreum",
    instagram: "https://instagram.com/agoreum",
    // The org page, not the repo: the repo is private, so a repo link 404s for
    // every visitor. The org is public and keeps working if repos are opened later.
    github: "https://github.com/agoreums",
  },
  chain: {
    name: "Base",
    id: 8453,
    currency: "USDC",
  },
} as const;

export const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Absolute URL builder, metadata and structured data must never emit relative URLs. */
export function absoluteUrl(path = "/"): string {
  const base = siteConfig.url.replace(/\/$/, "");
  return path.startsWith("/") ? `${base}${path}` : `${base}/${path}`;
}
