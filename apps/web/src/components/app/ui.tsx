import type { ButtonHTMLAttributes, ReactNode } from "react";

/**
 * The authenticated app's shared primitives.
 *
 * One definition each for the button, card, control, badge and skeleton, so every
 * screen draws from the same spec rather than a copied class string that drifts.
 * Focus is not set here: the global `:focus-visible` rule already gives the whole
 * product one consistent focus ring.
 */

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-2 rounded-xl text-sm font-medium transition-colors disabled:opacity-60 disabled:pointer-events-none";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-brand-600 px-5 py-2.5 text-white hover:bg-brand-500",
  secondary:
    "border border-[var(--border-subtle)] px-4 py-2.5 text-[var(--text-primary)] hover:border-[var(--border-strong)]",
  danger:
    "border border-danger-500/50 px-4 py-2.5 text-danger-500 hover:bg-danger-500/5",
  ghost: "px-3 py-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
};

export function Button({
  variant = "primary",
  className = "",
  type = "button",
  ...props
}: { variant?: ButtonVariant } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={type}
      className={`${BUTTON_BASE} ${BUTTON_VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

export function Card({
  className = "",
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={`rounded-[var(--radius-card)] border border-[var(--border-subtle)] ${className}`}
    >
      {children}
    </div>
  );
}

/** The canonical control styling, shared by inputs, selects and textareas. */
export const controlClass =
  "block w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-base)] px-4 py-2.5 text-sm outline-none transition-colors focus:border-brand-500";

type BadgeTone = "neutral" | "brand" | "success" | "danger" | "warning";

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: "border-[var(--border-subtle)] text-[var(--text-muted)]",
  brand: "border-brand-500/40 text-brand-500",
  success: "border-success-500/40 text-success-500",
  danger: "border-danger-500/40 text-danger-500",
  warning: "border-warning-500/40 text-warning-500",
};

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: BadgeTone;
  children: ReactNode;
}) {
  return (
    <span
      className={`inline-block shrink-0 rounded-full border px-2 py-0.5 text-xs ${BADGE_TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`animate-pulse rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] ${className}`}
    />
  );
}
