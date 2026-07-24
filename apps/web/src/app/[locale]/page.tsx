import { getTranslations, setRequestLocale } from "next-intl/server";

import { WebSiteJsonLd } from "@/components/seo/json-ld";
import { Link } from "@/i18n/navigation";
import { locales } from "@/i18n/routing";

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

export default async function HomePage(props: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  const t = await getTranslations("home");
  const tMeta = await getTranslations("metadata");

  const principles = ["custody", "escrow", "reputation", "identity"] as const;

  return (
    <>
      <WebSiteJsonLd description={tMeta("description")} />

      {/* ---------------------------------------------------------------- Hero */}
      <section className="relative overflow-hidden">
        <div
          aria-hidden="true"
          className="brand-glow pointer-events-none absolute inset-x-0 -top-32 h-[36rem]"
        />
        <div className="relative mx-auto max-w-7xl px-4 pb-20 pt-20 sm:px-6 sm:pt-28 lg:px-8">
          <div className="max-w-3xl">
            {/* The "Built on Base" badge was moved out of the hero into the
                documentation, where the platform detail can be explained. The
                hero leads with the product, not the plumbing. */}
            <h1 className="text-balance text-[length:var(--text-display)] font-semibold leading-[var(--text-display--line-height)] tracking-[var(--text-display--letter-spacing)]">
              {t("hero.title")}{" "}
              <span className="text-gradient-brand">
                {t("hero.titleAccent")}
              </span>
            </h1>

            <p className="mt-7 max-w-2xl text-pretty text-base leading-relaxed text-[var(--text-secondary)] sm:text-lg">
              {t("hero.subtitle")}
            </p>

            <div className="mt-10 flex flex-col gap-3 sm:flex-row">
              <Link
                href="/marketplace"
                className="inline-flex items-center justify-center rounded-xl bg-brand-600 px-6 py-3.5 text-sm font-medium text-white shadow-[var(--shadow-panel)] transition-colors duration-200 ease-[var(--ease-out-brand)] hover:bg-brand-500"
              >
                {t("hero.ctaPrimary")}
              </Link>
              <Link
                href="/agents/register"
                className="inline-flex items-center justify-center rounded-xl border border-[var(--border-strong)] px-6 py-3.5 text-sm font-medium text-[var(--text-primary)] transition-colors duration-200 ease-[var(--ease-out-brand)] hover:bg-[var(--surface-raised)]"
              >
                {t("hero.ctaSecondary")}
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------- Principles */}
      <section
        aria-labelledby="principles-heading"
        className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8"
      >
        <h2
          id="principles-heading"
          className="max-w-2xl text-balance text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2--line-height)] tracking-[var(--text-h2--letter-spacing)]"
        >
          {t("principles.title")}
        </h2>

        <ul className="mt-10 grid gap-4 sm:grid-cols-2">
          {principles.map((key) => (
            <li
              key={key}
              className="rounded-[var(--radius-panel)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-7"
            >
              <h3 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
                {t(`principles.${key}.title`)}
              </h3>
              <p className="mt-3 text-pretty text-sm leading-relaxed text-[var(--text-secondary)]">
                {t(`principles.${key}.body`)}
              </p>
            </li>
          ))}
        </ul>
      </section>

      {/* -------------------------------------------------------------- Status */}
      <section
        aria-labelledby="status-heading"
        className="mx-auto max-w-7xl px-4 pb-8 sm:px-6 lg:px-8"
      >
        <div className="rounded-[var(--radius-panel)] border border-[var(--border-subtle)] p-7 sm:p-9">
          <h2
            id="status-heading"
            className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]"
          >
            {t("status.title")}
          </h2>
          <p className="mt-3 max-w-3xl text-pretty text-sm leading-relaxed text-[var(--text-secondary)]">
            {t("status.body")}
          </p>
        </div>
      </section>
    </>
  );
}
