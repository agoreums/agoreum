"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button, controlClass } from "@/components/app/ui";
import { useAuth } from "@/components/auth/auth-provider";
import { localeNames, locales } from "@/i18n/routing";
import { ApiError, authApi } from "@/lib/api";

/**
 * Account preferences that live server-side.
 *
 * The communications language is stored on the account and drives the language of
 * notifications and email, distinct from the interface language chosen under
 * Appearance, which is a per-visit choice. Saving it persists to the account so it
 * follows the user across devices.
 */
export function PreferencesView() {
  const t = useTranslations("settingsPreferences");
  const { status, user, accessToken, refreshUser } = useAuth();

  const [locale, setLocale] = useState(user?.preferred_locale ?? "en");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  if (status !== "authenticated" || !user) {
    return (
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
        <p className="text-[var(--text-secondary)]">{t("signInRequired")}</p>
      </div>
    );
  }

  async function save() {
    if (!accessToken) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await authApi.updateProfile(accessToken, { preferred_locale: locale });
      await refreshUser();
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-xl space-y-6">
      <label className="block">
        <span className="text-sm font-medium text-[var(--text-primary)]">
          {t("communicationsLanguage")}
        </span>
        <span className="mt-0.5 block text-xs text-[var(--text-muted)]">
          {t("communicationsHint")}
        </span>
        <select
          value={locale}
          onChange={(e) => {
            setLocale(e.target.value);
            setSaved(false);
          }}
          className={`mt-2 ${controlClass}`}
        >
          {locales.map((l) => (
            <option key={l} value={l}>
              {localeNames[l]}
            </option>
          ))}
        </select>
      </label>

      {error ? <p className="text-sm text-danger-500">{error}</p> : null}
      {saved ? <p className="text-sm text-success-500">{t("saved")}</p> : null}

      <Button
        onClick={save}
        disabled={busy || locale === user.preferred_locale}
      >
        {busy ? t("saving") : t("save")}
      </Button>
    </div>
  );
}
