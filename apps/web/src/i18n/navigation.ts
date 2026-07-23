import { createNavigation } from "next-intl/navigation";

import { routing } from "./routing";

/**
 * Locale-aware navigation primitives.
 *
 * Always import `Link`, `redirect`, `useRouter`, and `usePathname` from here
 * rather than from `next/link` or `next/navigation` — these variants preserve
 * the active locale across navigation automatically.
 */
export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
