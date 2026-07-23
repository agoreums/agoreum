import type { ReactNode } from "react";

/**
 * Root layout.
 *
 * The real `<html>` element is rendered by `app/[locale]/layout.tsx`, which is the
 * only place that knows the active locale and text direction. This file exists
 * because Next requires a root layout, and it deliberately does nothing else.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return children;
}
