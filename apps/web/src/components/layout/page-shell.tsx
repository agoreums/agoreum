import type { ReactNode } from "react";

/**
 * Standard chrome for content pages: a constrained column with a title and lede,
 * consistent spacing, and comfortable measure for reading. Keeps the docs, legal,
 * and info pages visually of a piece rather than each inventing its own layout.
 */
export function PageShell({
  title,
  lede,
  children,
}: {
  title: string;
  lede?: string;
  children: ReactNode;
}) {
  return (
    <div className="mx-auto max-w-3xl px-4 py-16 sm:px-6 sm:py-20 lg:px-8">
      <header className="max-w-2xl">
        <h1 className="text-[length:var(--text-h1)] font-semibold leading-[var(--text-h1--line-height)] tracking-[var(--text-h1--letter-spacing)]">
          {title}
        </h1>
        {lede ? (
          <p className="mt-5 text-pretty text-lg leading-relaxed text-[var(--text-secondary)]">
            {lede}
          </p>
        ) : null}
      </header>
      <div className="mt-12 space-y-10 text-[15px] leading-relaxed text-[var(--text-secondary)]">
        {children}
      </div>
    </div>
  );
}

/** A titled prose section. */
export function Section({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)] text-[var(--text-primary)]">
        {heading}
      </h2>
      <div className="mt-3 space-y-3">{children}</div>
    </section>
  );
}
