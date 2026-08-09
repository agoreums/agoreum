"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Button, controlClass } from "@/components/app/ui";
import { useAuth } from "@/components/auth/auth-provider";
import { ApiError, ordersApi, type Dispute } from "@/lib/api";

/**
 * A dispute, shown the same way to the buyer, the provider and the arbiter.
 *
 * One view for all three is deliberate. Divergent views would mean somebody is
 * deciding, or being decided about, on a different set of facts, and the point
 * of showing each side the other's statements is that a decision made on
 * evidence one party never saw is not defensible.
 *
 * The reasoning appears here once a decision exists. It is shown to these three
 * and published nowhere.
 */
export function DisputePanel({ orderId }: { orderId: string }) {
  const t = useTranslations("dispute");
  const { accessToken } = useAuth();
  const [dispute, setDispute] = useState<Dispute | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    void ordersApi
      .dispute(accessToken, orderId)
      .then((d) => {
        if (!cancelled) {
          setDispute(d);
          setError(null);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        // A 404 means there is no dispute on this order, which is the ordinary
        // case and not an error worth showing anybody.
        if (err instanceof ApiError && err.status === 404) setDispute(null);
        else setError(err instanceof ApiError ? err.message : t("loadFailed"));
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken, orderId, t]);

  async function submit() {
    if (!accessToken || !text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setDispute(await ordersApi.submitDisputeStatement(accessToken, orderId, text.trim()));
      setText("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("submitFailed"));
    } finally {
      setBusy(false);
    }
  }

  if (!dispute) return null;

  const decided = dispute.decided_at !== null;

  return (
    <section className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-5">
      <h3 className="text-sm font-semibold">{t("title")}</h3>

      {dispute.reason ? (
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          {t("reasonLabel")}: {dispute.reason}
        </p>
      ) : null}

      {!decided && dispute.statements_close_at ? (
        <p className="mt-1 text-xs text-[var(--text-muted)]">
          {t("closes", {
            date: new Date(dispute.statements_close_at).toLocaleString(),
          })}
        </p>
      ) : null}

      <ol className="mt-4 space-y-3">
        {dispute.statements.map((s) => (
          <li
            key={s.id}
            className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-3"
          >
            <p className="text-xs text-[var(--text-muted)]">
              {new Date(s.created_at).toLocaleString()}
            </p>
            {/* Written by the other party. Rendered as text, never as markup. */}
            <p className="mt-1 whitespace-pre-wrap text-sm">{s.text}</p>
          </li>
        ))}
      </ol>

      {decided ? (
        <div className="mt-4 rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-4">
          <p className="text-sm font-semibold">{t("decided")}</p>
          <dl className="mt-2 grid gap-1 text-sm">
            <div className="flex justify-between">
              <dt className="text-[var(--text-muted)]">{t("toProvider")}</dt>
              <dd className="font-mono">{dispute.provider_amount}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-[var(--text-muted)]">{t("toBuyer")}</dt>
              <dd className="font-mono">{dispute.buyer_amount}</dd>
            </div>
          </dl>
          {dispute.reasoning ? (
            <p className="mt-3 whitespace-pre-wrap text-sm text-[var(--text-secondary)]">
              {dispute.reasoning}
            </p>
          ) : null}
          <p className="mt-3 text-xs text-[var(--text-muted)]">{t("settlementNote")}</p>
        </div>
      ) : (
        <div className="mt-4">
          <label className="text-xs text-[var(--text-muted)]" htmlFor="dispute-statement">
            {t("statementLabel")}
          </label>
          <textarea
            id="dispute-statement"
            value={text}
            maxLength={4000}
            rows={4}
            onChange={(e) => setText(e.target.value)}
            className={`${controlClass} mt-1.5 resize-y`}
          />
          <p className="mt-1.5 text-xs text-[var(--text-muted)]">{t("statementHint")}</p>
          <Button className="mt-2" onClick={submit} disabled={busy || !text.trim()}>
            {busy ? t("submitting") : t("submit")}
          </Button>
        </div>
      )}

      {error ? <p className="mt-3 text-sm text-danger-500">{error}</p> : null}
    </section>
  );
}
