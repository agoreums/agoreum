"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { Icon } from "@/components/app/icons";
import { useAuth } from "@/components/auth/auth-provider";
import { truncateAddress } from "@/components/auth/connect-wallet";
import { Link } from "@/i18n/navigation";

/**
 * The account menu: identity at a glance, the account-scoped destinations, and
 * sign out. Every link resolves to a real page; entries are added here as their
 * screens land rather than pointing at placeholders.
 */
const links = [
  { key: "settings", href: "/settings", icon: "settings" as const },
  { key: "apiKeys", href: "/settings/api-keys", icon: "key" as const },
  { key: "docs", href: "/docs", icon: "external" as const },
];

export function UserMenu() {
  const t = useTranslations("app.userMenu");
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click and Escape; navigating via a menu link closes it too.
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;

  const name =
    user.display_name || user.username || truncateAddress(user.primary_address);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-2 rounded-xl border border-[var(--border-subtle)] py-1.5 pl-1.5 pr-2.5 text-sm transition-colors hover:border-[var(--border-strong)]"
      >
        <span className="grid size-7 place-items-center rounded-lg bg-brand-500/15 text-brand-500">
          <Icon name="user" size={16} />
        </span>
        <span className="hidden max-w-[10rem] truncate font-medium sm:block">
          {name}
        </span>
        <Icon name="chevronDown" size={14} className="text-[var(--text-muted)]" />
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute end-0 z-50 mt-2 w-64 overflow-hidden rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-base)] shadow-xl"
        >
          <div className="border-b border-[var(--border-subtle)] px-4 py-3">
            <p className="truncate text-sm font-medium text-[var(--text-primary)]">
              {name}
            </p>
            <p className="mt-0.5 truncate font-mono text-xs text-[var(--text-muted)]">
              {truncateAddress(user.primary_address)}
            </p>
          </div>

          <div className="py-1.5">
            {links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                role="menuitem"
                onClick={() => setOpen(false)}
                className="flex items-center gap-3 px-4 py-2 text-sm text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text-primary)]"
              >
                <Icon name={link.icon} size={16} className="text-[var(--text-muted)]" />
                {t(link.key)}
              </Link>
            ))}
          </div>

          <div className="border-t border-[var(--border-subtle)] py-1.5">
            <button
              type="button"
              role="menuitem"
              onClick={() => void signOut()}
              className="flex w-full items-center gap-3 px-4 py-2 text-sm text-danger-500 transition-colors hover:bg-[var(--surface-raised)]"
            >
              <Icon name="logout" size={16} />
              {t("signOut")}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
