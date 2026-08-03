"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState, type ReactNode } from "react";

import { AppSidebar } from "@/components/app/app-sidebar";
import { Icon } from "@/components/app/icons";
import { UserMenu } from "@/components/app/user-menu";
import { useAuth } from "@/components/auth/auth-provider";
import { ConnectWalletButton } from "@/components/auth/connect-wallet";
import { LogoMarkStandalone, LogoWordmark } from "@/components/brand/logo";
import { LocaleSwitcher } from "@/components/layout/locale-switcher";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { siteConfig } from "@/lib/site";

/**
 * The persistent application shell.
 *
 * A permanent left sidebar on desktop, a slide-out drawer on tablet and mobile,
 * and a top header, all mounted once and kept across navigation, only the content
 * area changes. The shell is the boundary between the marketing site and the
 * product: it renders nothing marketing, and requires a signed-in session before
 * it shows any navigation at all.
 */
const SIDEBAR_WIDTH = "16rem";

export function AppShell({ children }: { children: ReactNode }) {
  const t = useTranslations("app");
  const { status } = useAuth();
  const [drawerOpen, setDrawerOpen] = useState(false);

  // The drawer is transient: every navigation control inside it closes it via
  // `onNavigate`, and it locks body scroll while open so the content behind it
  // cannot be scrolled by mistake.
  useEffect(() => {
    if (!drawerOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setDrawerOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", onKey);
    };
  }, [drawerOpen]);

  if (status === "loading" || status === "authenticating") {
    return (
      <div className="grid min-h-dvh place-items-center px-4">
        <div className="flex flex-col items-center gap-4">
          <LogoWordmark priority />
          <p className="text-sm text-[var(--text-muted)]">{t("loading")}</p>
        </div>
      </div>
    );
  }

  if (status !== "authenticated") {
    return (
      <div className="grid min-h-dvh place-items-center px-4">
        <div className="w-full max-w-md rounded-[var(--radius-panel)] border border-[var(--border-subtle)] bg-[var(--surface-base)] p-8 text-center">
          <LogoWordmark priority className="justify-center" />
          <h1 className="mt-6 text-[length:var(--text-h2)] font-semibold tracking-[var(--text-h2--letter-spacing)]">
            {t("gate.title")}
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-[var(--text-secondary)]">
            {t("gate.body")}
          </p>
          <div className="mt-6 flex justify-center">
            <ConnectWalletButton />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-dvh">
      {/* Permanent sidebar, desktop only. */}
      <aside
        className="fixed inset-y-0 start-0 z-30 hidden w-64 border-e border-[var(--border-subtle)] bg-[var(--surface-base)] lg:block"
        style={{ width: SIDEBAR_WIDTH }}
      >
        <AppSidebar />
      </aside>

      {/* Slide-out drawer, tablet and mobile. */}
      {drawerOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label={t("nav.closeMenu")}
            onClick={() => setDrawerOpen(false)}
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
          />
          <div className="absolute inset-y-0 start-0 flex w-[min(18rem,85vw)] flex-col border-e border-[var(--border-subtle)] bg-[var(--surface-base)] shadow-2xl">
            <AppSidebar onNavigate={() => setDrawerOpen(false)} />
          </div>
        </div>
      ) : null}

      {/* Content column, offset by the sidebar on desktop. */}
      <div className="flex min-h-dvh flex-col lg:ms-64">
        <header className="sticky top-0 z-20 border-b border-[var(--border-subtle)] bg-[color-mix(in_oklab,var(--surface-base)_82%,transparent)] backdrop-blur-xl">
          <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              aria-label={t("nav.openMenu")}
              className="grid size-9 place-items-center rounded-xl border border-[var(--border-subtle)] text-[var(--text-secondary)] transition-colors hover:border-[var(--border-strong)] lg:hidden"
            >
              <Icon name="menu" />
            </button>

            {/* Same treatment as the marketing header: the mark alone, at size.
                The sidebar and the gate screens keep the full lockup, where the
                name is doing real work rather than crowding the mark. */}
            <div className="lg:hidden">
              <LogoMarkStandalone label={siteConfig.name} />
            </div>

            <div className="ms-auto flex items-center gap-2">
              <ThemeToggle />
              <LocaleSwitcher />
              <UserMenu />
            </div>
          </div>
        </header>

        <main id="main" className="flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
