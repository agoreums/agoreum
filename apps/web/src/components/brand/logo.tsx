import Image from "next/image";
import type { CSSProperties } from "react";

import { siteConfig } from "@/lib/site";

/**
 * The Agoreum mark.
 *
 * This renders the official brand asset generated from `brand/logo.png`. The mark
 * is final artwork and is deliberately *not* reproduced as hand-authored SVG paths
 * anywhere in the codebase — redrawing it would let the rendered logo drift away
 * from the canonical source file.
 */
export function LogoMark({
  className = "",
  size = 32,
  priority = false,
}: {
  className?: string;
  size?: number;
  priority?: boolean;
}) {
  return (
    <Image
      src="/icons/mark.png"
      alt=""
      aria-hidden="true"
      width={size}
      height={size}
      priority={priority}
      className={className}
    />
  );
}

export function LogoWordmark({
  className = "",
  priority = false,
}: {
  className?: string;
  priority?: boolean;
}) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <LogoMark size={30} priority={priority} className="shrink-0 rounded-md" />
      <span className="text-[1.0625rem] font-semibold tracking-[-0.02em] text-[var(--text-primary)]">
        {siteConfig.name}
      </span>
    </span>
  );
}

/**
 * Hero brand lockup: an enlarged mark with the wordmark typing itself in, letter
 * by letter. Used once, in the hero, where the reveal reads as a considered
 * entrance rather than a gimmick — the header keeps the static wordmark so it
 * never re-animates on navigation. Falls back to a static wordmark under
 * prefers-reduced-motion (handled in CSS).
 */
export function AnimatedBrandLockup({ className = "" }: { className?: string }) {
  const letters = siteConfig.name.split("");
  return (
    <span className={`inline-flex items-center gap-3.5 ${className}`}>
      <LogoMark size={52} priority className="shrink-0 rounded-xl" />
      <span
        aria-label={siteConfig.name}
        className="text-2xl font-semibold tracking-[-0.03em] text-[var(--text-primary)] sm:text-[1.75rem]"
      >
        {letters.map((ch, i) => (
          <span
            key={i}
            aria-hidden="true"
            className="wordmark-letter"
            style={{ "--i": i } as CSSProperties}
          >
            {ch}
          </span>
        ))}
      </span>
    </span>
  );
}
