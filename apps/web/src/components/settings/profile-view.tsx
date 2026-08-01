"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { truncateAddress } from "@/components/auth/connect-wallet";
import { useAuth } from "@/components/auth/auth-provider";
import { ApiError, authApi, type ProfileUpdate, type UserProfile } from "@/lib/api";

/**
 * The editable profile.
 *
 * Identity is anchored to the wallet, which is shown but never editable. The rest,
 * a display name, a username, an optional email, a bio and avatar, is saved
 * through the profile endpoint. Changing the email clears its verification until
 * it is proven again, which the interface states plainly.
 */
export function ProfileView() {
  const t = useTranslations("settingsProfile");
  const { status, user } = useAuth();

  if (status !== "authenticated" || !user) {
    return (
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
        <p className="text-[var(--text-secondary)]">{t("signInRequired")}</p>
      </div>
    );
  }

  // Keyed on identity so the form's initial values always reflect the loaded user.
  return <ProfileForm key={user.id} user={user} />;
}

function ProfileForm({ user }: { user: UserProfile }) {
  const t = useTranslations("settingsProfile");
  const { accessToken, refreshUser } = useAuth();

  const [displayName, setDisplayName] = useState(user.display_name ?? "");
  const [username, setUsername] = useState(user.username ?? "");
  const [email, setEmail] = useState(user.email ?? "");
  const [bio, setBio] = useState(user.bio ?? "");
  const [avatarUrl, setAvatarUrl] = useState(user.avatar_url ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const emailChanged = (email.trim() || null) !== (user.email ?? null);

  async function save() {
    if (!accessToken) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    const body: ProfileUpdate = {
      display_name: displayName.trim() || null,
      username: username.trim() || null,
      email: email.trim() || null,
      bio: bio.trim() || null,
      avatar_url: avatarUrl.trim() || null,
    };
    try {
      await authApi.updateProfile(accessToken, body);
      await refreshUser();
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="max-w-2xl space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <Field label={t("addressLabel")} hint={t("addressHint")}>
        <p className="rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-raised)] px-4 py-2.5 font-mono text-sm text-[var(--text-secondary)]">
          <span className="hidden sm:inline">{user.primary_address}</span>
          <span className="sm:hidden">{truncateAddress(user.primary_address)}</span>
        </p>
      </Field>

      <Field label={t("nameLabel")}>
        <input
          type="text"
          value={displayName}
          maxLength={64}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder={t("namePlaceholder")}
          className={inputClass}
        />
      </Field>

      <Field label={t("usernameLabel")} hint={t("usernameHint")}>
        <input
          type="text"
          value={username}
          maxLength={32}
          onChange={(e) => setUsername(e.target.value)}
          className={inputClass}
        />
      </Field>

      <Field
        label={t("emailLabel")}
        hint={t("emailHint")}
        aside={
          user.email ? (
            <span
              className={`rounded-full border px-2 py-0.5 text-xs ${
                user.email_verified_at
                  ? "border-success-500/40 text-success-500"
                  : "border-[var(--border-subtle)] text-[var(--text-muted)]"
              }`}
            >
              {user.email_verified_at ? t("emailVerified") : t("emailUnverified")}
            </span>
          ) : null
        }
      >
        <input
          type="email"
          value={email}
          maxLength={320}
          onChange={(e) => setEmail(e.target.value)}
          className={inputClass}
        />
        {emailChanged && email.trim() ? (
          <p className="mt-1.5 text-xs text-warning-500">{t("emailReverify")}</p>
        ) : null}
      </Field>

      <Field label={t("bioLabel")}>
        <textarea
          value={bio}
          maxLength={600}
          rows={4}
          onChange={(e) => setBio(e.target.value)}
          className={`${inputClass} resize-y`}
        />
      </Field>

      <Field label={t("avatarLabel")}>
        <input
          type="url"
          value={avatarUrl}
          maxLength={512}
          onChange={(e) => setAvatarUrl(e.target.value)}
          placeholder="https://"
          className={inputClass}
        />
      </Field>

      {error ? <p className="text-sm text-danger-500">{error}</p> : null}
      {saved ? <p className="text-sm text-success-500">{t("saved")}</p> : null}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={busy}
          className="inline-flex rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-500 disabled:opacity-60"
        >
          {busy ? t("saving") : t("save")}
        </button>
        <span className="text-xs text-[var(--text-muted)]">
          {t("memberSince")} {new Date(user.created_at).toLocaleDateString()}
        </span>
      </div>
    </form>
  );
}

const inputClass =
  "block w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-base)] px-4 py-2.5 text-sm outline-none focus:border-brand-500";

function Field({
  label,
  hint,
  aside,
  children,
}: {
  label: string;
  hint?: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-[var(--text-primary)]">
          {label}
        </span>
        {aside}
      </span>
      <span className="mt-2 block">{children}</span>
      {hint ? (
        <span className="mt-1.5 block text-xs text-[var(--text-muted)]">{hint}</span>
      ) : null}
    </label>
  );
}
