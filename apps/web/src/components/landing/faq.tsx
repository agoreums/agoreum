"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useTranslations } from "next-intl";
import { useState } from "react";

const EASE = [0.22, 1, 0.36, 1] as const;
const ITEMS = ["custody", "chains", "reputation", "fees", "open", "build"] as const;

export function Faq() {
  const t = useTranslations("home");
  const reduce = useReducedMotion();
  const [open, setOpen] = useState<string | null>(ITEMS[0]);

  return (
    <section
      aria-labelledby="faq-heading"
      className="mx-auto max-w-3xl px-4 py-20 sm:px-6 lg:px-8"
    >
      <h2
        id="faq-heading"
        className="text-balance text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2--line-height)] tracking-[var(--text-h2--letter-spacing)]"
      >
        {t("faq.title")}
      </h2>

      <ul className="mt-10 divide-y divide-[var(--border-subtle)] border-y border-[var(--border-subtle)]">
        {ITEMS.map((key) => {
          const isOpen = open === key;
          return (
            <li key={key}>
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : key)}
                aria-expanded={isOpen}
                className="flex w-full items-center justify-between gap-4 py-5 text-start"
              >
                <span className="text-sm font-medium text-[var(--text-primary)]">
                  {t(`faq.${key}.q`)}
                </span>
                <motion.span
                  aria-hidden="true"
                  animate={reduce ? undefined : { rotate: isOpen ? 45 : 0 }}
                  transition={{ duration: 0.25, ease: EASE }}
                  className="flex-none text-lg text-[var(--text-muted)]"
                >
                  +
                </motion.span>
              </button>
              <AnimatePresence initial={false}>
                {isOpen ? (
                  <motion.div
                    initial={reduce ? undefined : { height: 0, opacity: 0 }}
                    animate={reduce ? undefined : { height: "auto", opacity: 1 }}
                    exit={reduce ? undefined : { height: 0, opacity: 0 }}
                    transition={{ duration: 0.3, ease: EASE }}
                    className="overflow-hidden"
                  >
                    <p className="pb-5 pe-8 text-sm leading-relaxed text-[var(--text-secondary)]">
                      {t(`faq.${key}.a`)}
                    </p>
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
