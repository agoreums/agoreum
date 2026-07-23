import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";

export default async function LocaleNotFound() {
  const t = await getTranslations("errors.notFound");

  return (
    <div className="mx-auto flex max-w-2xl flex-col items-start px-4 py-28 sm:px-6 lg:px-8">
      <p className="font-mono text-sm text-[var(--text-muted)]">404</p>
      <h1 className="mt-3 text-[length:var(--text-h1)] font-semibold leading-[var(--text-h1--line-height)] tracking-[var(--text-h1--letter-spacing)]">
        {t("title")}
      </h1>
      <p className="mt-4 text-pretty leading-relaxed text-[var(--text-secondary)]">
        {t("body")}
      </p>
      <Link
        href="/"
        className="mt-8 inline-flex items-center justify-center rounded-xl bg-brand-600 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-brand-500"
      >
        {t("action")}
      </Link>
    </div>
  );
}
