"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Link } from "@/i18n/navigation";

import { Reveal } from "./motion";

// Real, working examples against the public API — no fictional SDK. cURL and a
// plain HTTP call in each language, which is exactly what works today.
const TABS: { key: string; label: string; code: string }[] = [
  {
    key: "curl",
    label: "cURL",
    code: `curl https://agoreum.xyz/api/v1/me \\
  -H "X-API-Key: $AGOREUM_API_KEY"`,
  },
  {
    key: "python",
    label: "Python",
    code: `import requests

r = requests.get(
    "https://agoreum.xyz/api/v1/me",
    headers={"X-API-Key": AGOREUM_API_KEY},
)
print(r.json()["auth"]["scopes"])`,
  },
  {
    key: "typescript",
    label: "TypeScript",
    code: `const res = await fetch("https://agoreum.xyz/api/v1/me", {
  headers: { "X-API-Key": process.env.AGOREUM_API_KEY! },
});
const me = await res.json();
console.log(me.auth.scopes);`,
  },
];

export function DeveloperExperience() {
  const t = useTranslations("home");
  const [tab, setTab] = useState(TABS[0]!.key);
  const active = TABS.find((x) => x.key === tab) ?? TABS[0]!;

  return (
    <section
      aria-labelledby="developer-heading"
      className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8"
    >
      <div className="grid items-center gap-10 lg:grid-cols-2">
        <Reveal>
          <h2
            id="developer-heading"
            className="max-w-xl text-balance text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2--line-height)] tracking-[var(--text-h2--letter-spacing)]"
          >
            {t("developer.title")}
          </h2>
          <p className="mt-4 max-w-xl text-pretty leading-relaxed text-[var(--text-secondary)]">
            {t("developer.subtitle")}
          </p>
          <ul className="mt-6 space-y-2.5 text-sm text-[var(--text-secondary)]">
            {["keys", "scopes", "webhooks"].map((k) => (
              <li key={k} className="flex items-start gap-2.5">
                <span
                  aria-hidden="true"
                  className="mt-2 h-1.5 w-1.5 flex-none rounded-full bg-signal-500"
                />
                {t(`developer.points.${k}`)}
              </li>
            ))}
          </ul>
          <div className="mt-8">
            <Link
              href="/docs/api"
              className="inline-flex items-center justify-center rounded-xl border border-[var(--border-strong)] px-5 py-2.5 text-sm font-medium text-[var(--text-primary)] transition-colors hover:bg-[var(--surface-raised)]"
            >
              {t("developer.ctaDocs")}
            </Link>
          </div>
        </Reveal>

        <Reveal delay={0.1}>
          <div className="overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border-subtle)] bg-[var(--surface-raised)]">
            <div
              role="tablist"
              aria-label={t("developer.title")}
              className="flex gap-1 border-b border-[var(--border-subtle)] p-2"
            >
              {TABS.map((x) => (
                <button
                  key={x.key}
                  type="button"
                  role="tab"
                  aria-selected={x.key === tab}
                  onClick={() => setTab(x.key)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                    x.key === tab
                      ? "bg-[var(--surface-overlay)] text-[var(--text-primary)]"
                      : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                  }`}
                >
                  {x.label}
                </button>
              ))}
            </div>
            <pre className="overflow-x-auto p-5 font-mono text-[13px] leading-relaxed text-[var(--text-primary)]">
              <code>{active.code}</code>
            </pre>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
