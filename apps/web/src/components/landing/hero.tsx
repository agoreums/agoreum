"use client";

import { motion, useReducedMotion } from "framer-motion";
import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * Landing hero.
 *
 * A quiet, staged entrance — kicker, headline, subtitle, actions, then a row of
 * factual trust chips — with a single ambient light behind it. No mascots, no
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
      <div
        aria-hidden="true"
        className="brand-glow pointer-events-none absolute inset-x-0 -top-32 h-[36rem]"
      />
      <div className="relative mx-auto max-w-7xl px-4 pb-16 pt-20 sm:px-6 sm:pt-28 lg:px-8">
        <div className="max-w-3xl">
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

          <motion.ul
            {...rise(0.32)}
            className="mt-10 flex flex-wrap gap-x-6 gap-y-2 text-sm text-[var(--text-muted)]"
          >
            {chips.map((chip) => (
              <li key={chip} className="inline-flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className="h-1.5 w-1.5 rounded-full bg-signal-500"
                />
                {chip}
              </li>
            ))}
          </motion.ul>
        </div>
      </div>
    </section>
  );
}
