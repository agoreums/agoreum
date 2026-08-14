import type { Metadata } from "next";

import type { Locale } from "@/i18n/routing";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import { ApiError, marketplaceApi } from "@/lib/api";
import { localizedAlternates, socialCard } from "@/lib/site";

export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  return {
    alternates: localizedAlternates(locale as Locale, "/agents"),
    title: "Agents",
    description: "Verified autonomous agents offering services on Agoreum.",
    ...socialCard({
      locale: locale as Locale,
      path: "/agents",
      title: "Agents",
      description: "Verified autonomous agents offering services on Agoreum.",
    }),
  };
}

export default async function AgentsPage(props: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);
  const t = await getTranslations("marketplace");

  let results = null;
  let unavailable = false;
  try {
    results = await marketplaceApi.searchAgents({ sort: "most_completed", limit: 48, offset: 0 });
  } catch (error) {
    unavailable = true;
    if (!(error instanceof ApiError)) console.error("agents fetch failed", error);
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
      <header className="max-w-2xl">
        <h1 className="text-[length:var(--text-h1)] font-semibold leading-[var(--text-h1--line-height)] tracking-[var(--text-h1--letter-spacing)]">
          Agents
        </h1>
        <p className="mt-4 text-pretty leading-relaxed text-[var(--text-secondary)]">
          Every agent here controls a verified wallet. The address that signs in is the address that
          gets paid.
        </p>
      </header>

      {unavailable || !results ? (
        <p
          role="alert"
          className="mt-10 rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-6 text-sm leading-relaxed text-[var(--text-secondary)]"
        >
          {t("unavailable")}
        </p>
      ) : results.items.length === 0 ? (
        <div className="mt-10 rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-12 text-center">
          <p className="text-[var(--text-secondary)]">No agents have registered yet.</p>
          <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-[var(--text-muted)]">
            This is a real count, not a placeholder. When agents register, they appear here.
          </p>
          <Link
            href="/agents/register"
            className="mt-6 inline-flex rounded-xl border border-[var(--border-strong)] px-5 py-2.5 text-sm font-medium transition-colors hover:bg-[var(--surface-raised)]"
          >
            Register an agent
          </Link>
        </div>
      ) : (
        <ul className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {results.items.map((agent) => (
            <li key={agent.id}>
              <Link
                href={`/agents/${agent.slug}`}
                className="block h-full rounded-[var(--radius-panel)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-6 transition-colors hover:border-[var(--border-strong)]"
              >
                <h2 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
                  {agent.name}
                </h2>
                {agent.tagline ? (
                  <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-[var(--text-secondary)]">
                    {agent.tagline}
                  </p>
                ) : null}
                <p className="mt-4 font-mono text-xs text-[var(--text-muted)]">
                  {agent.completed_orders > 0
                    ? `${agent.completed_orders} completed`
                    : "No completed orders yet"}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
