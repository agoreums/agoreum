// This file renders outside any locale segment, so there is no active locale to
// preserve and the locale-aware Link from @/i18n/navigation cannot be used here.
// eslint-disable-next-line no-restricted-imports
import Link from "next/link";

/**
 * Global 404, rendered for paths that never resolved to a locale (so no message
 * catalogue is available). Deliberately English-only and dependency-free.
 */
export default function GlobalNotFound() {
  return (
    <html lang="en">
      <body
        style={{
          background: "#0A0A12",
          color: "#F6F7FB",
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
          display: "flex",
          minHeight: "100dvh",
          alignItems: "center",
          justifyContent: "center",
          margin: 0,
          padding: "2rem",
        }}
      >
        <div style={{ maxWidth: "32rem" }}>
          <p style={{ color: "#848DB3", fontSize: "0.875rem", margin: 0 }}>404</p>
          <h1 style={{ fontSize: "2rem", margin: "0.5rem 0 1rem", letterSpacing: "-0.02em" }}>
            Page not found
          </h1>
          <p style={{ color: "#B0B7D0", lineHeight: 1.6, margin: "0 0 2rem" }}>
            The page you are looking for does not exist or has been moved.
          </p>
          <Link href="/" style={{ color: "#868CF8" }}>
            Return home
          </Link>
        </div>
      </body>
    </html>
  );
}
