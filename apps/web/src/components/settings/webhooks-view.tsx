"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Button, controlClass } from "@/components/app/ui";
import { useAuth } from "@/components/auth/auth-provider";
import { OrgSelect } from "@/components/settings/org-select";
import {
  ApiError,
  webhooksApi,
  type WebhookDelivery,
  type WebhookEndpoint,
  type WebhookEndpointCreated,
  type WebhookEvent,
} from "@/lib/api";

const WILDCARD = "*";

/**
 * Webhook endpoint management.
 *
 * Mirrors the API-key screen: the signing secret is shown exactly once, at
 * creation, and never again. Everything else is metadata, url, subscribed
 * events, delivery health, and each endpoint can expand to its recent deliveries.
 */
export function WebhooksView() {
  const t = useTranslations("webhooks");
  const { status, accessToken } = useAuth();

  const [catalog, setCatalog] = useState<WebhookEvent[]>([]);
  const [endpoints, setEndpoints] = useState<WebhookEndpoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The active organization, empty string for the caller's personal org.
  const [org, setOrg] = useState("");
  const [reload, setReload] = useState(0);
  const refresh = () => setReload((n) => n + 1);

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) return;
    let cancelled = false;

    async function run() {
      try {
        const [cat, list] = await Promise.all([
          webhooksApi.events(),
          webhooksApi.list(accessToken!, org || undefined),
        ]);
        if (cancelled) return;
        setCatalog(cat.events);
        setEndpoints(list.items);
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

      <CreateEndpoint
        catalog={catalog}
        accessToken={accessToken!}
        orgSlug={org || undefined}
        onCreated={refresh}
      />

      <EndpointList
        endpoints={endpoints}
        accessToken={accessToken!}
        orgSlug={org || undefined}
        onChanged={refresh}
      />
    </div>
  );
}

function CreateEndpoint({
  catalog,
  accessToken,
  orgSlug,
  onCreated,
}: {
  catalog: WebhookEvent[];
  accessToken: string;
  orgSlug?: string;
  onCreated: () => void;
}) {
  const t = useTranslations("webhooks");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [allEvents, setAllEvents] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [created, setCreated] = useState<WebhookEndpointCreated | null>(null);

  function toggle(event: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(event)) next.delete(event);
      else next.add(event);
      return next;
    });
  }

  async function submit() {
    if (!url.trim().startsWith("https://")) {
      setFormError(t("urlHttps"));
      return;
    }
    const events = allEvents ? [WILDCARD] : [...selected];
    if (events.length === 0) {
      setFormError(t("eventRequired"));
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      const endpoint = await webhooksApi.create(
        accessToken,
        {
          url: url.trim(),
          events,
          description: description.trim() || null,
        },
        orgSlug,
      );
      setCreated(endpoint);
      setUrl("");
      setDescription("");
      setAllEvents(true);
      setSelected(new Set());
      onCreated();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : t("createFailed"));
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return <CreatedEndpoint created={created} onDone={() => setCreated(null)} />;
  }

  return (
    <section className="rounded-[var(--radius-panel)] border border-[var(--border-subtle)] p-6">
      <h2 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
        {t("createTitle")}
      </h2>
      <p className="mt-2 text-sm text-[var(--text-secondary)]">{t("createHint")}</p>

      <div className="mt-6 space-y-6">
        <label className="block">
          <span className="text-sm font-medium">{t("urlLabel")}</span>
          <input
            type="url"
            value={url}
            maxLength={2048}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={t("urlPlaceholder")}
            className={`mt-2 ${controlClass}`}
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium">{t("descriptionLabel")}</span>
          <input
            type="text"
            value={description}
            maxLength={100}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t("descriptionPlaceholder")}
            className={`mt-2 ${controlClass}`}
          />
        </label>

        <fieldset>
          <legend className="text-sm font-medium">{t("eventsLabel")}</legend>
          <label className="mt-3 flex cursor-pointer items-start gap-3 rounded-xl border border-[var(--border-subtle)] p-3 transition-colors hover:border-brand-500">
            <input
              type="checkbox"
              checked={allEvents}
              onChange={(e) => setAllEvents(e.target.checked)}
              className="mt-0.5 size-4 accent-brand-600"
            />
            <span>
              <span className="text-sm font-medium">{t("allEvents")}</span>
              <span className="mt-0.5 block text-xs text-[var(--text-muted)]">
                {t("allEventsHint")}
              </span>
            </span>
          </label>

          {!allEvents ? (
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {catalog.map((e) => (
                <label
                  key={e.event}
                  className="flex cursor-pointer items-start gap-3 rounded-xl border border-[var(--border-subtle)] p-3 transition-colors hover:border-brand-500"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(e.event)}
                    onChange={() => toggle(e.event)}
                    className="mt-0.5 size-4 accent-brand-600"
                  />
                  <span>
                    <code className="text-xs font-medium text-[var(--text-primary)]">
                      {e.event}
                    </code>
                    <span className="mt-0.5 block text-xs text-[var(--text-muted)]">
                      {e.description}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          ) : null}
        </fieldset>

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

function CreatedEndpoint({
  created,
  onDone,
}: {
  created: WebhookEndpointCreated;
  onDone: () => void;
}) {
  const t = useTranslations("webhooks");
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(created.secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard can be unavailable; the secret is on screen to copy manually.
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

      <p className="mt-4 text-xs font-medium text-[var(--text-muted)]">
        {t("secretLabel")}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <code className="grow overflow-x-auto rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-base)] px-4 py-3 font-mono text-sm">
          {created.secret}
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

function EndpointList({
  endpoints,
  accessToken,
  orgSlug,
  onChanged,
}: {
  endpoints: WebhookEndpoint[];
  accessToken: string;
  orgSlug?: string;
  onChanged: () => void;
}) {
  const t = useTranslations("webhooks");

  if (endpoints.length === 0) {
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
      <ul className="mt-4 space-y-3">
        {endpoints.map((e) => (
          <EndpointRow
            key={e.id}
            endpoint={e}
            accessToken={accessToken}
            orgSlug={orgSlug}
            onChanged={onChanged}
          />
        ))}
      </ul>
    </section>
  );
}

function EndpointRow({
  endpoint,
  accessToken,
  orgSlug,
  onChanged,
}: {
  endpoint: WebhookEndpoint;
  accessToken: string;
  orgSlug?: string;
  onChanged: () => void;
}) {
  const t = useTranslations("webhooks");
  const [busy, setBusy] = useState(false);
  const [showDeliveries, setShowDeliveries] = useState(false);
  const [deliveries, setDeliveries] = useState<WebhookDelivery[] | null>(null);
  const revoked = endpoint.revoked_at !== null;

  async function revoke() {
    if (!window.confirm(t("revokeConfirm", { url: endpoint.url }))) return;
    setBusy(true);
    try {
      await webhooksApi.revoke(accessToken, endpoint.id, orgSlug);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function loadDeliveries() {
    setShowDeliveries((v) => !v);
    if (deliveries === null) {
      try {
        setDeliveries(await webhooksApi.deliveries(accessToken, endpoint.id, orgSlug));
      } catch {
        setDeliveries([]);
      }
    }
  }

  return (
    <li
      className={`rounded-[var(--radius-card)] border border-[var(--border-subtle)] px-5 py-4 ${
        revoked ? "opacity-60" : ""
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <code className="break-all font-mono text-sm text-[var(--text-primary)]">
              {endpoint.url}
            </code>
            {revoked ? (
              <span className="rounded-full bg-[var(--surface-raised)] px-2 py-0.5 text-xs text-[var(--text-muted)]">
                {t("statusRevoked")}
              </span>
            ) : null}
          </div>
          {endpoint.description ? (
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              {endpoint.description}
            </p>
          ) : null}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {endpoint.events.map((ev) => (
              <code
                key={ev}
                className="rounded bg-[var(--surface-raised)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-secondary)]"
              >
                {ev === WILDCARD ? t("allEventsTag") : ev}
              </code>
            ))}
          </div>
          <p className="mt-2 text-xs text-[var(--text-muted)]">
            {endpoint.last_success_at
              ? t("lastSuccess", {
                  when: new Date(endpoint.last_success_at).toLocaleString(),
                })
              : t("neverDelivered")}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="secondary" onClick={loadDeliveries} className="px-4 py-2">
            {t("deliveriesToggle")}
          </Button>
          {!revoked ? (
            <Button
              variant="danger"
              onClick={revoke}
              disabled={busy}
              className="px-4 py-2"
            >
              {busy ? t("revoking") : t("revoke")}
            </Button>
          ) : null}
        </div>
      </div>

      {showDeliveries ? (
        <div className="mt-4 border-t border-[var(--border-subtle)] pt-4">
          {deliveries === null ? (
            <p className="text-xs text-[var(--text-muted)]">{t("loading")}</p>
          ) : deliveries.length === 0 ? (
            <p className="text-xs text-[var(--text-muted)]">{t("noDeliveries")}</p>
          ) : (
            <ul className="space-y-2">
              {deliveries.map((d) => (
                <li
                  key={d.id}
                  className="flex flex-wrap items-center justify-between gap-2 text-xs"
                >
                  <span className="flex items-center gap-2">
                    <code className="font-mono text-[var(--text-secondary)]">
                      {d.event_type}
                    </code>
                    <StatusPill status={d.status} />
                  </span>
                  <span className="text-[var(--text-muted)]">
                    {t("attemptCount", { n: d.attempts, max: d.max_attempts })}
                    {d.last_status_code ? ` · HTTP ${d.last_status_code}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </li>
  );
}

function StatusPill({ status }: { status: string }) {
  const t = useTranslations("webhooks");
  const labels: Record<string, string> = {
    pending: t("statusPending"),
    succeeded: t("statusSucceeded"),
    failed: t("statusFailed"),
    exhausted: t("statusExhausted"),
    suppressed: t("statusSuppressed"),
  };
  const tone =
    status === "succeeded"
      ? "text-success-500"
      : status === "failed" || status === "exhausted"
        ? "text-danger-500"
        : "text-[var(--text-muted)]";
  return <span className={`font-medium ${tone}`}>{labels[status] ?? status}</span>;
}
