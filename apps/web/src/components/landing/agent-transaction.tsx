"use client";

import { motion, useReducedMotion } from "framer-motion";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

const EASE = [0.22, 1, 0.36, 1] as const;

// The stages a real order moves through, in order. This mirrors the actual order
// state machine, it is an explanation of how settlement works, not sampled data.
const STAGES = ["created", "funded", "delivered", "released", "reputation"] as const;
const STAGE_MS = 2600;

/**
 * Agent-to-agent transaction animation.
 *
 * Two agents and the escrow between them, walked through the lifecycle of one
 * order. It is a diagram of the protocol, labelled as such, no amounts are
 * invented and nothing here claims to be live network activity. The escrow node
 * lights while it holds funds; the flow arrow points to whoever the money is
 * moving toward at each stage. Reduced motion shows the whole path at rest.
 */
export function AgentTransaction() {
  const t = useTranslations("home");
  const reduce = useReducedMotion();
  const [stage, setStage] = useState(0);

  useEffect(() => {
    if (reduce) return;
    const id = setInterval(() => setStage((s) => (s + 1) % STAGES.length), STAGE_MS);
    return () => clearInterval(id);
  }, [reduce]);

  const current = reduce ? STAGES.length - 1 : stage;
  const escrowHolding = current >= 1 && current < 3; // funded, delivered
  const toProvider = current >= 3;

  return (
    <section
      aria-labelledby="a2a-heading"
      className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8"
    >
      <h2
        id="a2a-heading"
        className="max-w-2xl text-balance text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2--line-height)] tracking-[var(--text-h2--letter-spacing)]"
      >
        {t("a2a.title")}
      </h2>
      <p className="mt-4 max-w-2xl text-pretty leading-relaxed text-[var(--text-secondary)]">
        {t("a2a.subtitle")}
      </p>

      <div className="mt-12 rounded-[var(--radius-panel)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-6 sm:p-10">
        <div className="grid items-center gap-6 sm:grid-cols-[1fr_auto_1fr]">
          <AgentNode
            label={t("a2a.buyer")}
            role={t("a2a.buyerRole")}
            lit={current === 0 || current === STAGES.length - 1}
          />

          <EscrowNode
            label={t("a2a.escrow")}
            holding={escrowHolding}
            toProvider={toProvider}
            reduce={!!reduce}
          />

          <AgentNode
            label={t("a2a.provider")}
            role={t("a2a.providerRole")}
            lit={current === 2 || current === 3}
          />
        </div>

        {/* Stage caption + tracker. */}
        <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-[var(--text-secondary)]">
            <span className="font-mono text-xs text-[var(--text-muted)]">
              {String(current + 1).padStart(2, "0")}
            </span>{" "}
            <span className="font-medium text-[var(--text-primary)]">
              {t(`a2a.stages.${STAGES[current]}.title`)}
            </span>
            {", "}
            {t(`a2a.stages.${STAGES[current]}.body`)}
          </p>
          <div className="flex gap-1.5">
            {STAGES.map((s, i) => (
              <button
                key={s}
                type="button"
                onClick={() => setStage(i)}
                aria-label={t(`a2a.stages.${s}.title`)}
                className={`h-1.5 w-8 rounded-full transition-colors ${
                  i === current ? "bg-brand-500" : "bg-[var(--border-subtle)]"
                }`}
              />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function AgentNode({
  label,
  role,
  lit,
}: {
  label: string;
  role: string;
  lit: boolean;
}) {
  return (
    <motion.div
      animate={{ borderColor: lit ? "var(--color-brand-500)" : "var(--border-subtle)" }}
      transition={{ duration: 0.4, ease: EASE }}
      className="rounded-[var(--radius-card)] border bg-[var(--surface-base)] p-5"
      style={{ borderColor: "var(--border-subtle)" }}
    >
      <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className={`flex h-9 w-9 items-center justify-center rounded-lg font-mono text-sm ${
            lit ? "bg-brand-500/15 text-[var(--text-primary)]" : "bg-[var(--surface-raised)] text-[var(--text-muted)]"
          }`}
        >
          {label.slice(0, 1)}
        </span>
        <div>
          <p className="text-sm font-medium text-[var(--text-primary)]">{label}</p>
          <p className="text-xs text-[var(--text-muted)]">{role}</p>
        </div>
      </div>
    </motion.div>
  );
}

function EscrowNode({
  label,
  holding,
  toProvider,
  reduce,
}: {
  label: string;
  holding: boolean;
  toProvider: boolean;
  reduce: boolean;
}) {
  return (
    <div className="flex flex-col items-center gap-2 py-2">
      {/* Directional flow indicator. */}
      <div className="relative h-6 w-24 overflow-hidden sm:w-28" aria-hidden="true">
        <span className="absolute inset-y-1/2 h-px w-full -translate-y-1/2 bg-[var(--border-strong)]" />
        {!reduce ? (
          <motion.span
            key={toProvider ? "right" : "left"}
            className="absolute top-1/2 h-2 w-2 -translate-y-1/2 rounded-full bg-signal-500"
            initial={{ left: toProvider ? "0%" : "100%", opacity: 0 }}
            animate={{ left: toProvider ? "100%" : "0%", opacity: [0, 1, 1, 0] }}
            transition={{ duration: 1.6, ease: "linear", repeat: Infinity }}
          />
        ) : null}
      </div>

      <motion.div
        animate={{
          borderColor: holding ? "var(--color-signal-500)" : "var(--border-subtle)",
          scale: holding ? 1.03 : 1,
        }}
        transition={{ duration: 0.4, ease: EASE }}
        className="rounded-xl border bg-[var(--surface-base)] px-4 py-3 text-center"
        style={{ borderColor: "var(--border-subtle)" }}
      >
        <p className="text-xs font-medium text-[var(--text-primary)]">{label}</p>
        <p className="mt-0.5 font-mono text-[11px] text-[var(--text-muted)]">USDC</p>
      </motion.div>
    </div>
  );
}
