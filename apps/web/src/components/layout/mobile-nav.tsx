"use client";

import { useEffect, useRef, useState } from "react";

import { LocaleSwitcher } from "@/components/layout/locale-switcher";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Link } from "@/i18n/navigation";
import { siteConfig } from "@/lib/site";
import {
  DiscordIcon,
  GitHubIcon,
  InstagramIcon,
  RedditIcon,
  TelegramIcon,
  XIcon,
} from "@/components/brand/social-icons";

const mobileSocials = [
  { key: "x", label: "X", href: siteConfig.social.x, Icon: XIcon },
  { key: "discord", label: "Discord", href: siteConfig.social.discord, Icon: DiscordIcon },
  { key: "reddit", label: "Reddit", href: siteConfig.social.reddit, Icon: RedditIcon },
  { key: "telegram", label: "Telegram", href: siteConfig.social.telegram, Icon: TelegramIcon },
  { key: "instagram", label: "Instagram", href: siteConfig.social.instagram, Icon: InstagramIcon },
  { key: "github", label: "GitHub", href: siteConfig.social.github, Icon: GitHubIcon },
] as const;

type NavItem = { href: string; label: string };

/**
 * Mobile navigation drawer.
 *
 * Uses a native `<dialog>` so the browser supplies the focus trap, the inert
 * background, and Escape-to-close rather than reimplementing all three imperfectly.
 */
export function MobileNav({
  items,
  menuLabel,
  closeLabel,
}: {
  items: readonly NavItem[];
  menuLabel: string;
  closeLabel: string;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={menuLabel}
        aria-expanded={open}
        className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text-primary)] md:hidden"
      >
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          className="h-5 w-5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
        >
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
      </button>

      <dialog
        ref={dialogRef}
        onClose={() => setOpen(false)}
        onClick={(e) => {
          // Clicking the backdrop (the dialog element itself) dismisses the drawer.
          if (e.target === dialogRef.current) setOpen(false);
        }}
        className="m-0 ml-auto h-dvh max-h-none w-[min(20rem,85vw)] max-w-none bg-[var(--surface-raised)] p-0 text-[var(--text-primary)] backdrop:bg-black/60 backdrop:backdrop-blur-sm"
      >
        <div className="flex h-full flex-col p-5">
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label={closeLabel}
              className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-overlay)] hover:text-[var(--text-primary)]"
            >
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                className="h-5 w-5"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
              >
                <path d="m6 6 12 12M18 6 6 18" />
              </svg>
            </button>
          </div>

          <nav aria-label="Mobile" className="mt-2 flex flex-col gap-1">
            {items.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                // Closed here rather than in an effect on pathname: navigation is
                // the only way to leave the drawer, so this is the direct cause
                // and avoids a cascading render after the route changes.
                onClick={() => setOpen(false)}
                className="rounded-lg px-3 py-3 text-base text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-overlay)] hover:text-[var(--text-primary)]"
              >
                {item.label}
              </Link>
            ))}
          </nav>

          <div className="mt-auto space-y-4 border-t border-[var(--border-subtle)] pt-4">
            <div className="flex items-center justify-between gap-3">
              <ThemeToggle />
              <LocaleSwitcher />
            </div>
            <ul className="flex flex-wrap items-center gap-1">
              {mobileSocials.map((social) => (
                <li key={social.key}>
                  <a
                    href={social.href}
                    target="_blank"
                    rel="me noopener noreferrer"
                    aria-label={social.label}
                    title={social.label}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-overlay)] hover:text-[var(--text-primary)]"
                  >
                    <social.Icon />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </dialog>
    </>
  );
}
