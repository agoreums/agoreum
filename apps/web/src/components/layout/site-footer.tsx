import { getTranslations } from "next-intl/server";

import { LogoMark } from "@/components/brand/logo";
import {
  DiscordIcon,
  GitHubIcon,
  InstagramIcon,
  RedditIcon,
  TelegramIcon,
  XIcon,
} from "@/components/brand/social-icons";
import { Link } from "@/i18n/navigation";
import { siteConfig } from "@/lib/site";

const socialLinks = [
  { key: "x", label: "X", href: siteConfig.social.x, Icon: XIcon },
  { key: "discord", label: "Discord", href: siteConfig.social.discord, Icon: DiscordIcon },
  { key: "reddit", label: "Reddit", href: siteConfig.social.reddit, Icon: RedditIcon },
  { key: "telegram", label: "Telegram", href: siteConfig.social.telegram, Icon: TelegramIcon },
  { key: "instagram", label: "Instagram", href: siteConfig.social.instagram, Icon: InstagramIcon },
  { key: "github", label: "GitHub", href: siteConfig.social.github, Icon: GitHubIcon },
] as const;

export async function SiteFooter() {
  const t = await getTranslations("footer");
  const year = new Date().getFullYear();

  const columns = [
    {
      heading: t("product"),
      links: [
        { label: t("documentation"), href: "/docs" },
        { label: t("security"), href: "/security" },
      ],
    },
    {
      heading: t("company"),
      links: [
        { label: t("contact"), href: "/contact" },
        { label: t("support"), href: "/support" },
      ],
    },
    {
      heading: t("legal"),
      links: [
        { label: t("privacy"), href: "/privacy" },
        { label: t("terms"), href: "/terms" },
      ],
    },
  ];

  return (
    <footer className="mt-24 border-t border-[var(--border-subtle)]">
      <div className="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:px-8">
        <div className="grid gap-12 md:grid-cols-[1.5fr_repeat(3,1fr)]">
          <div className="max-w-xs">
            <div className="flex items-center gap-2.5">
              <LogoMark size={28} className="rounded-md" />
              <span className="text-[1.0625rem] font-semibold tracking-[-0.02em]">
                {siteConfig.name}
              </span>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-[var(--text-muted)]">
              {t("tagline")}
            </p>
            <p className="mt-4 inline-flex items-center gap-1.5 rounded-full border border-[var(--border-subtle)] px-2.5 py-1 text-xs text-[var(--text-muted)]">
              <span
                aria-hidden="true"
                className="h-1.5 w-1.5 rounded-full bg-brand-500"
              />
              {t("builtOn")}
            </p>
          </div>

          {columns.map((column) => (
            <nav key={column.heading} aria-label={column.heading}>
              <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                {column.heading}
              </h2>
              <ul className="mt-4 space-y-2.5">
                {column.links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="text-sm text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>

        <div className="mt-12 flex flex-col gap-4 border-t border-[var(--border-subtle)] pt-6 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-[var(--text-muted)]">
            © {year} {siteConfig.name}. {t("rights")}
          </p>
          <ul className="flex flex-wrap items-center gap-2">
            {socialLinks.map((social) => (
              <li key={social.key}>
                <a
                  href={social.href}
                  target="_blank"
                  rel="me noopener noreferrer"
                  aria-label={social.label}
                  title={social.label}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text-primary)]"
                >
                  <social.Icon />
                </a>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </footer>
  );
}
