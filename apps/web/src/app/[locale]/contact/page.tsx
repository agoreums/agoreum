import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

import { PageShell, Section } from "@/components/layout/page-shell";
import {
  DiscordIcon,
  GitHubIcon,
  RedditIcon,
  TelegramIcon,
  XIcon,
} from "@/components/brand/social-icons";
import { siteConfig } from "@/lib/site";

export const metadata: Metadata = {
  title: "Contact",
  description: "How to reach the Agoreum team and community.",
};

const channels = [
  { label: "X", href: siteConfig.social.x, Icon: XIcon },
  { label: "Discord", href: siteConfig.social.discord, Icon: DiscordIcon },
  { label: "Reddit", href: siteConfig.social.reddit, Icon: RedditIcon },
  { label: "Telegram", href: siteConfig.social.telegram, Icon: TelegramIcon },
  { label: "GitHub", href: siteConfig.social.github, Icon: GitHubIcon },
];

export default async function ContactPage(props: { params: Promise<{ locale: string }> }) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  return (
    <PageShell title="Contact" lede="Questions, partnerships, or feedback are welcome.">
      <Section heading="Email">
        <p>
          For enquiries, support, and anything else, reach us at{" "}
          <a className="text-[var(--text-primary)] underline decoration-[var(--border-strong)] underline-offset-4 hover:decoration-current" href={`mailto:${siteConfig.supportEmail}`}>
            {siteConfig.supportEmail}
          </a>
          .
        </p>
      </Section>

      <Section heading="Community">
        <ul className="mt-2 flex flex-wrap gap-2">
          {channels.map((c) => (
            <li key={c.label}>
              <a
                href={c.href}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] px-3.5 py-2 text-sm text-[var(--text-secondary)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
              >
                <c.Icon width={16} height={16} />
                {c.label}
              </a>
            </li>
          ))}
        </ul>
      </Section>
    </PageShell>
  );
}
