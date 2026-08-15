"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Button, controlClass } from "@/components/app/ui";
import { useAuth } from "@/components/auth/auth-provider";
import { OrgSelect } from "@/components/settings/org-select";
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
 * user must dismiss, the API never returns it again. Everything else here is
 * metadata: prefix, scopes, and lifecycle timestamps, never the secret.
 */
export function ApiKeysView() {
  const t = useTranslations("apiKeys");
  const { status, accessToken } = useAuth();

  const [catalog, setCatalog] = useState<ApiKeyScope[]>([]);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The active organization, empty string for the caller's personal org. Keys are
  // scoped to it, so switching orgs reloads the list.
  const [org, setOrg] = useState("");
  // Bumped after a create or revoke to re-run the loader. Keeping the fetch inside
  // the effect, rather than in a callback the effect calls, is what lets the
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
          apiKeysApi.list(accessToken!, org || undefined),
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
  }, [status, accessToken, org, reload, t]);

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
      <OrgSelect accessToken={accessToken!} value={org} onChange={setOrg} />

      {error ? (
        <p className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-4 text-sm text-danger-500">
          {error}
        </p>
      ) : null}

      <CreateKey
        catalog={catalog}
        accessToken={accessToken!}
        orgSlug={org || undefined}
        onCreated={refresh}
      />

      <KeyList
        keys={keys}
        accessToken={accessToken!}
        orgSlug={org || undefined}
        onChanged={refresh}
      />
    </div>
  );
}

/** Whether a scope lets a key change something rather than only look at it.
 *
 * Derived from the scope string rather than kept as a list here, so a scope
 * added to the API's catalogue later is flagged the day it appears instead of
 * the day somebody remembers this file. The naming convention is the contract:
 * `resource:write`. */
function isWriteScope(scope: string): boolean {
  return scope.endsWith(":write");
}

function CreateKey({
  catalog,
  accessToken,
  orgSlug,
  onCreated,
}: {
  catalog: ApiKeyScope[];
  accessToken: string;
  orgSlug?: string;
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
      const key = await apiKeysApi.create(
        accessToken,
        {
          name: name.trim(),
          scopes: [...selected],
          expires_in_days: expiry === "never" ? null : Number(expiry),
        },
        orgSlug,
      );
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
            className={`mt-2 ${controlClass}`}
          />
        </label>

        <fieldset>
          <legend className="text-sm font-medium">{t("scopesLabel")}</legend>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {catalog.map((s) => {
              const writes = isWriteScope(s.scope);
              return (
                <label
                  key={s.scope}
                  className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors hover:border-brand-500 ${
                    writes && selected.has(s.scope)
                      ? "border-amber-500/60 bg-amber-500/5"
                      : "border-[var(--border-subtle)]"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(s.scope)}
                    onChange={() => toggle(s.scope)}
                    className="mt-0.5 size-4 accent-brand-600"
                  />
                  <span>
                    <span className="flex flex-wrap items-center gap-2">
                      <code className="text-xs font-medium text-[var(--text-primary)]">
                        {s.scope}
                      </code>
                      {writes && (
                        <span className="rounded-full border border-amber-500/50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-600 dark:text-amber-400">
                          {t("writeBadge")}
                        </span>
                      )}
                    </span>
                    <span className="mt-0.5 block text-xs text-[var(--text-muted)]">
                      {s.description}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>

          {/* Shown only once a write scope is actually ticked. A warning that is
              always on the page is furniture, and gets read as decoration; one
              that appears in response to the choice being made is about that
              choice. The scope descriptions from the API say what a scope does,
              which is not the same as saying what it costs if the key leaks. */}
          {[...selected].some(isWriteScope) && (
            <p
              role="status"
              className="mt-3 rounded-xl border border-amber-500/50 bg-amber-500/5 p-3 text-xs text-[var(--text-secondary)]"
            >
              <strong className="font-medium text-amber-600 dark:text-amber-400">
                {t("writeWarningTitle")}
              </strong>{" "}
              {t("writeWarning")}
            </p>
          )}
        </fieldset>

        <label className="block max-w-xs">
          <span className="text-sm font-medium">{t("expiryLabel")}</span>
          <select
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            className={`mt-2 ${controlClass}`}
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

        <Button onClick={submit} disabled={busy}>
          {busy ? t("creating") : t("create")}
        </Button>
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
        <Button variant="secondary" onClick={copy} className="px-4 py-3">
          {copied ? t("copied") : t("copy")}
        </Button>
      </div>

      <Button onClick={onDone} className="mt-6">
        {t("createdDone")}
      </Button>
    </section>
  );
}

function KeyList({
  keys,
  accessToken,
  orgSlug,
  onChanged,
}: {
  keys: ApiKey[];
  accessToken: string;
  orgSlug?: string;
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
            orgSlug={orgSlug}
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
  orgSlug,
  onChanged,
}: {
  apiKey: ApiKey;
  accessToken: string;
  orgSlug?: string;
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
      await apiKeysApi.revoke(accessToken, apiKey.id, orgSlug);
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
          <Button
            variant="danger"
            onClick={revoke}
            disabled={busy}
            className="shrink-0 px-4 py-2"
          >
            {busy ? t("revoking") : t("revoke")}
          </Button>
        ) : null}
      </div>
    </li>
  );
}
