"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { orgsApi, type Organization } from "@/lib/api";

/**
 * Chooses which organization a scoped screen (API keys, webhooks) operates on.
 *
 * The value is a slug, or the empty string for the caller's personal
 * organization, which is what the API treats as the default. The control hides
 * itself when the user belongs to only their personal org, so a solo creator
 * never sees a switcher with a single choice.
 */
export function OrgSelect({
  accessToken,
  value,
  onChange,
}: {
  accessToken: string;
  value: string;
  onChange: (slug: string) => void;
}) {
  const t = useTranslations("organizations");
  const [orgs, setOrgs] = useState<Organization[]>([]);

  useEffect(() => {
    let cancelled = false;
    orgsApi
      .list(accessToken)
      .then((list) => {
        if (!cancelled) setOrgs(list);
      })
      .catch(() => {
        // A failure here just means no switcher; the scoped screen still works
        // against the personal org and surfaces its own errors.
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  if (orgs.length <= 1) return null;

  return (
    <label className="flex flex-wrap items-center gap-2 text-sm">
      <span className="font-medium text-[var(--text-secondary)]">
        {t("switcher.label")}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-base)] px-3 py-2 text-sm outline-none focus:border-brand-500"
      >
        {orgs.map((o) => (
          <option key={o.slug} value={o.kind === "personal" ? "" : o.slug}>
            {o.kind === "personal" ? t("switcher.personal") : o.name}
          </option>
        ))}
      </select>
    </label>
  );
}
