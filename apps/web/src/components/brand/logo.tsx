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
