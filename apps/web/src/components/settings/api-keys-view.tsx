"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import {
  ApiError,
  apiKeysApi,
  type ApiKey,
  type ApiKeyCreated,
  type ApiKeyScope,
} from "@/lib/api";

/**
 * API key management.
 *
 * The plaintext key is shown exactly once, right after creation, in a panel the
 * user must dismiss — the API never returns it again. Everything else here is
 * metadata: prefix, scopes, and lifecycle timestamps, never the secret.
 */
export function ApiKeysView() {
  const t = useTranslations("apiKeys");
  const { status, accessToken } = useAuth();

  const [catalog, setCatalog] = useState<ApiKeyScope[]>([]);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Bumped after a create or revoke to re-run the loader. Keeping the fetch inside
  // the effect — rather than in a callback the effect calls — is what lets the
  // linter see that state is only ever set after an await, never on the render path.
  const [reload, setReload] = useState(0);
  const refresh = () => setReload((n) => n + 1);

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) return;
    let cancelled = false;

    async function run() {
      try {
        const [cat, list] = await Promise.all([
          apiKeysApi.scopes(),
          apiKeysApi.list(accessToken!),
        ]);
        if (cancelled) return;
        setCatalog(cat.scopes);
        setKeys(list.items);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : t("loadFailed"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, [status, accessToken, reload, t]);

  if (status !== "authenticated") {
    return (
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
        <p className="text-[var(--text-secondary)]">{t("signInRequired")}</p>
      </div>
    );
  }

  if (loading) {
    return <p className="text-[var(--text-muted)]">{t("loading")}</p>;
  }

  return (
    <div className="space-y-10">
      {error ? (
        <p className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-4 text-sm text-danger-500">
          {error}
        </p>
      ) : null}

      <CreateKey
        catalog={catalog}
        accessToken={accessToken!}
        onCreated={refresh}
      />

      <KeyList keys={keys} accessToken={accessToken!} onChanged={refresh} />
    </div>
  );
}

function CreateKey({
  catalog,
  accessToken,
  onCreated,
}: {
  catalog: ApiKeyScope[];
  accessToken: string;
  onCreated: () => void;
}) {
  const t = useTranslations("apiKeys");
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expiry, setExpiry] = useState<string>("never");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);

  function toggle(scope: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(scope)) next.delete(scope);
      else next.add(scope);
      return next;
    });
  }

  async function submit() {
    if (!name.trim()) {
      setFormError(t("nameRequired"));
      return;
    }
    if (selected.size === 0) {
      setFormError(t("scopeRequired"));
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      const key = await apiKeysApi.create(accessToken, {
        name: name.trim(),
        scopes: [...selected],
        expires_in_days: expiry === "never" ? null : Number(expiry),
      });
      setCreated(key);
      setName("");
      setSelected(new Set());
      setExpiry("never");
      onCreated();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : t("createFailed"));
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return <CreatedKey created={created} onDone={() => setCreated(null)} />;
  }

  return (
    <section className="rounded-[var(--radius-panel)] border border-[var(--border-subtle)] p-6">
      <h2 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
        {t("createTitle")}
      </h2>
      <p className="mt-2 text-sm text-[var(--text-secondary)]">{t("createHint")}</p>

      <div className="mt-6 space-y-6">
        <label className="block">
          <span className="text-sm font-medium">{t("nameLabel")}</span>
          <input
            type="text"
            value={name}
            maxLength={64}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("namePlaceholder")}
            className="mt-2 block w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-base)] px-4 py-2.5 text-sm outline-none focus:border-brand-500"
          />
        </label>

        <fieldset>
          <legend className="text-sm font-medium">{t("scopesLabel")}</legend>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {catalog.map((s) => (
              <label
                key={s.scope}
                className="flex cursor-pointer items-start gap-3 rounded-xl border border-[var(--border-subtle)] p-3 transition-colors hover:border-brand-500"
              >
                <input
                  type="checkbox"
                  checked={selected.has(s.scope)}
                  onChange={() => toggle(s.scope)}
                  className="mt-0.5 size-4 accent-brand-600"
                />
                <span>
                  <code className="text-xs font-medium text-[var(--text-primary)]">
                    {s.scope}
                  </code>
                  <span className="mt-0.5 block text-xs text-[var(--text-muted)]">
                    {s.description}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <label className="block max-w-xs">
          <span className="text-sm font-medium">{t("expiryLabel")}</span>
          <select
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            className="mt-2 block w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-base)] px-4 py-2.5 text-sm outline-none focus:border-brand-500"
          >
            <option value="never">{t("expiryNever")}</option>
            <option value="30">{t("expiryDays", { days: 30 })}</option>
            <option value="90">{t("expiryDays", { days: 90 })}</option>
            <option value="365">{t("expiryDays", { days: 365 })}</option>
          </select>
        </label>

        {formError ? (
          <p className="text-sm text-danger-500">{formError}</p>
        ) : null}

        <button
          type="button"
          onClick={submit}
          disabled={busy}
          className="inline-flex rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-500 disabled:opacity-60"
        >
          {busy ? t("creating") : t("create")}
        </button>
      </div>
    </section>
  );
}

function CreatedKey({
  created,
  onDone,
}: {
  created: ApiKeyCreated;
  onDone: () => void;
}) {
  const t = useTranslations("apiKeys");
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(created.token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard can be unavailable (insecure context, permissions). The token
      // is still on screen for the user to select manually, so this is not fatal.
    }
  }

  return (
    <section className="rounded-[var(--radius-panel)] border border-brand-500/40 bg-brand-500/5 p-6">
      <h2 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
        {t("createdTitle")}
      </h2>
      <p className="mt-2 text-sm text-[var(--text-secondary)]">
        {t("createdWarning")}
      </p>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <code className="grow overflow-x-auto rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-base)] px-4 py-3 font-mono text-sm">
          {created.token}
        </code>
        <button
          type="button"
          onClick={copy}
          className="rounded-xl border border-[var(--border-subtle)] px-4 py-3 text-sm font-medium transition-colors hover:border-brand-500"
        >
          {copied ? t("copied") : t("copy")}
        </button>
      </div>

      <button
        type="button"
        onClick={onDone}
        className="mt-6 inline-flex rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-500"
      >
        {t("createdDone")}
      </button>
    </section>
  );
}

function KeyList({
  keys,
  accessToken,
  onChanged,
}: {
  keys: ApiKey[];
  accessToken: string;
  onChanged: () => void;
}) {
  const t = useTranslations("apiKeys");

  if (keys.length === 0) {
    return (
      <p className="rounded-[var(--radius-card)] border border-dashed border-[var(--border-subtle)] p-8 text-center text-sm text-[var(--text-muted)]">
        {t("empty")}
      </p>
    );
  }

  return (
    <section>
      <h2 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
        {t("existingTitle")}
      </h2>
      <ul className="mt-4 divide-y divide-[var(--border-subtle)] rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
        {keys.map((k) => (
          <KeyRow
            key={k.id}
            apiKey={k}
            accessToken={accessToken}
            onChanged={onChanged}
          />
        ))}
      </ul>
    </section>
  );
}

function KeyRow({
  apiKey,
  accessToken,
  onChanged,
}: {
  apiKey: ApiKey;
  accessToken: string;
  onChanged: () => void;
}) {
  const t = useTranslations("apiKeys");
  const [busy, setBusy] = useState(false);
  const revoked = apiKey.revoked_at !== null;
  const expired =
    !revoked &&
    apiKey.expires_at !== null &&
    new Date(apiKey.expires_at) <= new Date();

  async function revoke() {
    if (!window.confirm(t("revokeConfirm", { name: apiKey.name }))) return;
    setBusy(true);
    try {
      await apiKeysApi.revoke(accessToken, apiKey.id);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={`px-5 py-4 ${revoked ? "opacity-60" : ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{apiKey.name}</span>
            <code className="rounded bg-[var(--surface-raised)] px-1.5 py-0.5 font-mono text-xs text-[var(--text-muted)]">
              {apiKey.prefix}…
            </code>
            {revoked ? (
              <span className="rounded-full bg-[var(--surface-raised)] px-2 py-0.5 text-xs text-[var(--text-muted)]">
                {t("statusRevoked")}
              </span>
            ) : expired ? (
              <span className="rounded-full bg-[var(--surface-raised)] px-2 py-0.5 text-xs text-[var(--text-muted)]">
                {t("statusExpired")}
              </span>
            ) : null}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {apiKey.scopes.map((s) => (
              <code
                key={s}
                className="rounded bg-[var(--surface-raised)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-secondary)]"
              >
                {s}
              </code>
            ))}
          </div>
          <p className="mt-2 text-xs text-[var(--text-muted)]">
            {apiKey.last_used_at
              ? t("lastUsed", {
                  when: new Date(apiKey.last_used_at).toLocaleDateString(),
                })
              : t("neverUsed")}
          </p>
        </div>
        {!revoked ? (
          <button
            type="button"
            onClick={revoke}
            disabled={busy}
            className="shrink-0 rounded-xl border border-[var(--border-subtle)] px-4 py-2 text-sm font-medium text-danger-500 transition-colors hover:border-danger-500 disabled:opacity-60"
          >
            {busy ? t("revoking") : t("revoke")}
          </button>
        ) : null}
      </div>
    </li>
  );
}
