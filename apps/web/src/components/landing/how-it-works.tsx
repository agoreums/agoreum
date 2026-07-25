"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

const EASE = [0.22, 1, 0.36, 1] as const;

const STEPS = [
  "connect",
  "verify",
  "publish",
  "discover",
  "purchase",
  "escrow",
  "reputation",
] as const;

const AUTO_ADVANCE_MS = 3800;

/**
 * Interactive "How it works".
 *
 * The seven stages of a transaction, as a stepper that advances on its own and
 * on click. The motion is doing explanatory work — it walks the eye through the
 * order of events — rather than decorating. Under reduced motion it becomes a
 * plain, fully expanded list with no auto-advance and no transitions.
 */
export function HowItWorks() {
  const t = useTranslations("home");
  const reduce = useReducedMotion();
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);

  const advance = useCallback(() => {
    setActive((i) => (i + 1) % STEPS.length);
  }, []);

  useEffect(() => {
    if (reduce || paused) return;
    const id = setInterval(advance, AUTO_ADVANCE_MS);
    return () => clearInterval(id);
  }, [reduce, paused, advance]);

  return (
    <section
      aria-labelledby="flow-heading"
      className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8"
    >
      <h2
        id="flow-heading"
        className="max-w-2xl text-balance text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2--line-height)] tracking-[var(--text-h2--letter-spacing)]"
      >
        {t("flow.title")}
      </h2>
      <p className="mt-4 max-w-2xl text-pretty leading-relaxed text-[var(--text-secondary)]">
        {t("flow.subtitle")}
      </p>

      {reduce ? (
        <ol className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map((step, i) => (
            <li
              key={step}
              className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-5"
            >
              <StepTitle index={i} label={t(`flow.${step}.title`)} active />
              <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                {t(`flow.${step}.body`)}
              </p>
            </li>
          ))}
        </ol>
      ) : (
        <div
          className="mt-12 grid gap-8 lg:grid-cols-[1.1fr_1fr]"
          onMouseEnter={() => setPaused(true)}
          onMouseLeave={() => setPaused(false)}
        >
          {/* The rail of steps. */}
          <ol className="flex flex-col gap-1.5">
            {STEPS.map((step, i) => {
              const isActive = i === active;
              return (
                <li key={step}>
                  <button
                    type="button"
                    onClick={() => setActive(i)}
                    aria-current={isActive ? "step" : undefined}
                    className="group flex w-full items-center gap-4 rounded-xl px-3 py-3 text-start transition-colors hover:bg-[var(--surface-raised)]"
                  >
                    <StepTitle index={i} label={t(`flow.${step}.title`)} active={isActive} />
                  </button>
                </li>
              );
            })}
          </ol>

          {/* The detail panel for the active step. */}
          <div className="relative min-h-[15rem] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-7">
            <AnimatePresence mode="wait">
              <motion.div
                key={active}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.4, ease: EASE }}
              >
                <span className="font-mono text-xs text-[var(--text-muted)]">
                  {String(active + 1).padStart(2, "0")} / {STEPS.length}
                </span>
                <h3 className="mt-3 text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
                  {t(`flow.${STEPS[active]}.title`)}
                </h3>
                <p className="mt-3 text-pretty leading-relaxed text-[var(--text-secondary)]">
                  {t(`flow.${STEPS[active]}.body`)}
                </p>
              </motion.div>
            </AnimatePresence>

            {/* Progress dots. */}
            <div className="absolute inset-x-7 bottom-6 flex gap-1.5">
              {STEPS.map((step, i) => (
                <span
                  key={step}
                  className="h-1 flex-1 overflow-hidden rounded-full bg-[var(--border-subtle)]"
                >
                  <motion.span
                    className="block h-full bg-brand-500"
                    initial={false}
                    animate={{ scaleX: i <= active ? 1 : 0 }}
                    style={{ transformOrigin: "left" }}
                    transition={{ duration: 0.4, ease: EASE }}
                  />
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function StepTitle({
  index,
  label,
  active,
}: {
  index: number;
  label: string;
  active: boolean;
}) {
  return (
    <span className="flex items-center gap-3">
      <span
        aria-hidden="true"
        className={`flex h-8 w-8 flex-none items-center justify-center rounded-full border font-mono text-xs transition-colors ${
          active
            ? "border-brand-500 bg-brand-500/10 text-[var(--text-primary)]"
            : "border-[var(--border-strong)] text-[var(--text-muted)]"
        }`}
      >
        {index + 1}
      </span>
      <span
        className={`text-sm font-medium transition-colors ${
          active ? "text-[var(--text-primary)]" : "text-[var(--text-secondary)]"
        }`}
      >
        {label}
      </span>
    </span>
  );
}
