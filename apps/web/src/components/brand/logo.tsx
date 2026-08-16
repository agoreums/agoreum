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
 * shrinks the one element that actually carries the identity.
 *
 * Freed of it, the mark takes 44px on a phone and 52px in the 72px desktop bar,
 * a little over 70% of the header's height. The previous 40/44 in a 64px bar was
 * reviewed against the rest of the header and read as an afterthought: at that
 * size it sat below the visual weight of the wallet button beside it, so the
 * first thing the eye found on the page was a control rather than the identity.
 * A mark this size is the deliberate anchor of the bar.
 *
 * The intrinsic size is deliberately far larger than either rendered size so the
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
        size={160}
        priority={priority}
        className="h-11 w-11 shrink-0 sm:h-13 sm:w-13"
      />
      <span className="sr-only">{label}</span>
    </span>
  );
}

/**
 * Mark and name together, for the places a bare mark is not enough context:
 * the application shell and the authenticated sidebar.
 *
 * The mark and the wordmark are set as two separate elements with real space
 * between them rather than a locked-up unit. Previously a 30px mark sat 10px from
 * 17px text, which is close enough that the two read as one crowded blob and the
 * mark loses its own silhouette. The standing decision on this build is that the
 * mark has to be able to stand alone, and it cannot do that while it is being
 * used as a bullet point in front of a word.
 *
 * So the mark is 38px, the gap is 14px, and the name is set slightly lighter in
 * weight. The mark leads, the name follows it.
 */
export function LogoWordmark({
  className = "",
  priority = false,
}: {
  className?: string;
  priority?: boolean;
}) {
  return (
    <span className={`inline-flex items-center gap-3.5 ${className}`}>
      <LogoMark size={120} priority={priority} className="h-9.5 w-9.5 shrink-0" />
      <span className="text-[1.125rem] font-semibold tracking-[-0.022em] text-[var(--text-primary)]">
        {siteConfig.name}
      </span>
    </span>
  );
}
