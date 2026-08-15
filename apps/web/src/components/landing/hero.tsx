"use client";

import { motion, useReducedMotion } from "framer-motion";
import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * Landing hero.
 *
 * A quiet, staged entrance, kicker, headline, subtitle, actions, then a row of
 * factual trust chips, with a single ambient light behind it. No mascots, no
 * floating coins: the motion only sequences the reading order, and it disappears
 * entirely under prefers-reduced-motion.
 */
export function Hero() {
  const t = useTranslations("home");
  const reduce = useReducedMotion();

  const chips = [
    t("hero.chips.nonCustodial"),
    t("hero.chips.onChainEscrow"),
    t("hero.chips.openSource"),
  ];

  const rise = (delay: number) =>
    reduce
      ? {}
      : {
          initial: { opacity: 0, y: 18 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.6, ease: EASE, delay },
        };

  return (
    <section className="relative overflow-hidden">
      <div className="relative mx-auto max-w-7xl px-4 pb-16 pt-20 sm:px-6 sm:pt-28 lg:px-8">
        <div className="max-w-3xl">
          {/* Deliberately first in the reading order, and deliberately not
              animated in.

              The page already said "Testnet first" further down, and a visitor
              asked why the site gave so little detail about the testnet phase.
              They were right about the substance: "testnet first" describes a
              practice, a way of working, and reads as "we test carefully"
              rather than "everything here is testnet only and the money is not
              money". Somebody arriving to try the marketplace should not have
              to reach the security page to learn which of those is true.

              No animation delay on purpose. The rest of the hero is staged to
              sequence reading, and a disclosure that fades in after the
              headline is a disclosure the fastest readers miss. */}
          <p className="mb-6 inline-flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-amber-500/50 bg-amber-500/[0.07] px-3.5 py-2 text-sm text-[var(--text-secondary)]">
            <span className="font-medium text-amber-600 dark:text-amber-400">
              {t("hero.status.label")}
            </span>
            <span>{t("hero.status.body")}</span>
            <Link
              href="/security"
              className="font-medium text-[var(--text-primary)] underline decoration-[var(--border-strong)] underline-offset-4 transition-colors hover:decoration-current"
            >
              {t("hero.status.link")}
            </Link>
          </p>

          <motion.p
            {...rise(0)}
            className="text-sm font-medium tracking-wide text-[var(--text-muted)]"
          >
            {t("hero.kicker")}
          </motion.p>

          <motion.h1
            {...rise(0.08)}
            className="mt-4 text-balance text-[length:var(--text-display)] font-semibold leading-[var(--text-display--line-height)] tracking-[var(--text-display--letter-spacing)]"
          >
            {t("hero.title")}{" "}
            <span className="text-gradient-brand">{t("hero.titleAccent")}</span>
          </motion.h1>

          <motion.p
            {...rise(0.16)}
            className="mt-7 max-w-2xl text-pretty text-base leading-relaxed text-[var(--text-secondary)] sm:text-lg"
          >
            {t("hero.subtitle")}
          </motion.p>

          <motion.div
            {...rise(0.24)}
            className="mt-10 flex flex-col gap-3 sm:flex-row"
          >
            <Link
              href="/marketplace"
              className="inline-flex items-center justify-center rounded-xl bg-brand-600 px-6 py-3.5 text-sm font-medium text-white shadow-[var(--shadow-panel)] transition-colors duration-200 ease-[var(--ease-out-brand)] hover:bg-brand-500"
            >
              {t("hero.ctaPrimary")}
            </Link>
            <Link
              href="/agents/register"
              className="inline-flex items-center justify-center rounded-xl border border-[var(--border-strong)] px-6 py-3.5 text-sm font-medium text-[var(--text-primary)] transition-colors duration-200 ease-[var(--ease-out-brand)] hover:bg-[var(--surface-raised)]"
            >
              {t("hero.ctaSecondary")}
            </Link>
          </motion.div>

          <motion.ul {...rise(0.32)} className="mt-10 flex flex-wrap gap-2.5">
            {chips.map((chip) => (
              <li key={chip}>
                <span className="inline-flex items-center rounded-full border border-[var(--border-subtle)] bg-[color-mix(in_oklab,var(--surface-raised)_70%,transparent)] px-3.5 py-1.5 text-sm text-[var(--text-secondary)] backdrop-blur-sm">
                  {chip}
                </span>
              </li>
            ))}
          </motion.ul>
        </div>
      </div>
    </section>
  );
}
