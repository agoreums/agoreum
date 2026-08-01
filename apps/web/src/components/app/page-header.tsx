import type { ReactNode } from "react";

/**
 * The standard heading for an application page: a title, an optional description,
 * and an optional cluster of actions. Using one component everywhere keeps every
 * screen's top matter aligned, spaced, and responsive in exactly the same way.
 */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="max-w-2xl">
        <h1 className="text-[length:var(--text-h1)] font-semibold leading-[var(--text-h1--line-height)] tracking-[var(--text-h1--letter-spacing)]">
          {title}
        </h1>
        {description ? (
          <p className="mt-2 text-pretty leading-relaxed text-[var(--text-secondary)]">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>
      ) : null}
    </header>
  );
}
