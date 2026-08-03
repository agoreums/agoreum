import Image from "next/image";

import { siteConfig } from "@/lib/site";

/**
 * The Agoreum mark.
 *
 * This renders the official brand asset generated from `brand/logo.png`. The mark
 * is final artwork and is deliberately *not* reproduced as hand-authored SVG paths
 * anywhere in the codebase, redrawing it would let the rendered logo drift away
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

/**
 * The mark standing on its own, at header scale.
 *
 * The site header carries no wordmark: the name is already the tab title, the
 * domain, and the first line of the footer, so repeating it beside the mark only
 * shrinks the one element that actually carries the identity. Freed of it, the
 * mark takes 40px on a phone and 44px in a 64px-tall bar, roughly two thirds of
 * the header's height, and reads as a deliberate mark rather than a favicon that
 * wandered onto the page.
 *
 * The intrinsic size is deliberately larger than either rendered size so the
 * image stays sharp on a phone's 2x or 3x display; CSS controls what is shown.
 *
 * `label` is not decoration. `LogoMark` is `aria-hidden`, so a home link built
 * only from the mark would reach a screen reader as an unnamed link. This renders
 * the name for assistive technology while keeping it off the screen.
 */
export function LogoMarkStandalone({
  label,
  priority = false,
}: {
  label: string;
  priority?: boolean;
}) {
  return (
    <span className="inline-flex items-center">
      <LogoMark
        size={132}
        priority={priority}
        className="h-10 w-10 shrink-0 sm:h-11 sm:w-11"
      />
      <span className="sr-only">{label}</span>
    </span>
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
