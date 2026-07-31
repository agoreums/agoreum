"use client";

import { useReducedMotion } from "framer-motion";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { Reveal } from "./motion";

// Real, verifiable platform facts, not vanity metrics and not sampled data.
// Each number is something you can check against the product itself.
const STATS: { key: string; value: number; suffix?: string; decimals?: number }[] = [
  { key: "locales", value: 9 },
  { key: "scopes", value: 7 },
  { key: "events", value: 7 },
  { key: "fee", value: 2.5, suffix: "%", decimals: 1 },
];

export function Stats() {
  const t = useTranslations("home");
  return (
    <section className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
      <Reveal>
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border-subtle)] bg-[var(--border-subtle)] sm:grid-cols-4">
          {STATS.map((stat) => (
            <div key={stat.key} className="bg-[var(--surface-base)] p-6 text-center">
              <dt className="sr-only">{t(`stats.${stat.key}`)}</dt>
              <dd>
                <CountUp
                  value={stat.value}
                  suffix={stat.suffix}
                  decimals={stat.decimals}
                />
                <span className="mt-1 block text-sm text-[var(--text-muted)]">
                  {t(`stats.${stat.key}`)}
                </span>
              </dd>
            </div>
          ))}
        </dl>
      </Reveal>
    </section>
  );
}

function CountUp({
  value,
  suffix,
  decimals = 0,
}: {
  value: number;
  suffix?: string;
  decimals?: number;
}) {
  const reduce = useReducedMotion();
  const [display, setDisplay] = useState(reduce ? value : 0);
  const ref = useRef<HTMLSpanElement>(null);
  const started = useRef(false);

  useEffect(() => {
    if (reduce || started.current) return;
    const node = ref.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting || started.current) return;
        started.current = true;
        const duration = 900;
        const start = performance.now();
        const tick = (now: number) => {
          const p = Math.min(1, (now - start) / duration);
          // easeOutCubic
          const eased = 1 - Math.pow(1 - p, 3);
          setDisplay(value * eased);
          if (p < 1) requestAnimationFrame(tick);
          else setDisplay(value);
        };
        requestAnimationFrame(tick);
      },
      { threshold: 0.4 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [reduce, value]);

  return (
    <span
      ref={ref}
      className="text-[length:var(--text-h1)] font-semibold tracking-[var(--text-h1--letter-spacing)] text-[var(--text-primary)]"
    >
      {display.toFixed(decimals)}
      {suffix ?? ""}
    </span>
  );
}
