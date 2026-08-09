"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Button, controlClass } from "@/components/app/ui";
import { useAuth } from "@/components/auth/auth-provider";
import {
  ApiError,
  adminApi,
  ordersApi,
  type DisputeQueueItem,
  type SettlementInstructions,
} from "@/lib/api";

/**
 * The arbiter's work queue.
 *
 * Oldest first, because every row is somebody's money held while they wait, and
 * a queue worked newest first leaves the person who has waited longest waiting
 * longer. The API orders it; this does not re-sort.
 *
 * Deciding does not settle. It records the decision and returns the exact call
 * for the arbiter's own wallet, because the platform holds no keys. The
 * instructions are shown rather than acted on.
 */
export function DisputeQueueView() {
  const t = useTranslations("arbiter");
  const { status, accessToken } = useAuth();
  const [rows, setRows] = useState<DisputeQueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) return;
    let cancelled = false;
    void adminApi
      .disputeQueue(accessToken)
      .then((list) => {
        if (!cancelled) {
          setRows(list);
          setError(null);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        // A refusal here is the ordinary case for anyone who is not the
        // arbiter, so it is stated plainly rather than shown as a fault.
        setRows([]);
        setError(
          err instanceof ApiError && err.status === 403
            ? t("notArbiter")
            : err instanceof ApiError
              ? err.message
              : t("loadFailed"),
        );
      });
    return () => {
      cancelled = true;
    };
  }, [status, accessToken, t]);

  if (status !== "authenticated") {
    return <p className="text-[var(--text-secondary)]">{t("signInRequired")}</p>;
  }
  if (rows === null) return <p className="text-[var(--text-muted)]">{t("loading")}</p>;

  return (
    <div className="space-y-6">
      {error ? <p className="text-sm text-[var(--text-secondary)]">{error}</p> : null}
      {rows.length === 0 && !error ? (
        <p className="text-[var(--text-secondary)]">{t("empty")}</p>
      ) : null}
      {rows.map((row) => (
        <DisputeCard key={row.order_id} row={row} accessToken={accessToken!} />
      ))}
    </div>
  );
}

function DisputeCard({
  row,
  accessToken,
}: {
  row: DisputeQueueItem;
  accessToken: string;
}) {
  const t = useTranslations("arbiter");
  const [providerAmount, setProviderAmount] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [instructions, setInstructions] = useState<SettlementInstructions | null>(null);

  // Derived here only to show the arbiter what the other side receives. The
  // figure sent is the provider's share alone; the contract computes this one,
  // and sending both would allow a decision that differs from what is paid.
  const buyerShown =
    providerAmount === "" || Number.isNaN(Number(providerAmount))
      ? null
      : (Number(row.amount) - Number(providerAmount)).toFixed(6);

  async function decide() {
    setBusy(true);
    setError(null);
    try {
      setInstructions(
        await ordersApi.decideDispute(accessToken, row.order_id, {
          provider_amount: providerAmount,
          reasoning: reasoning.trim(),
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("decideFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-mono text-sm">{row.order_reference}</h3>
        <span className="text-sm">
          {row.amount} {row.currency}
        </span>
      </div>
      <p className="mt-1 text-xs text-[var(--text-muted)]">
        {t("waiting", { hours: row.hours_waiting ?? 0 })}
      </p>
      {row.reason ? (
        <p className="mt-2 whitespace-pre-wrap text-sm text-[var(--text-secondary)]">
          {row.reason}
        </p>
      ) : null}

      {instructions ? (
        <div className="mt-4 rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-4">
          <p className="text-sm font-semibold">{t("recorded")}</p>
          <p className="mt-1 text-xs text-[var(--text-muted)]">{t("recordedHint")}</p>
          {/*
            An LTR island. This is a Solidity call signature with hex addresses
            and base-unit integers, which an operator may copy verbatim. Under
            an RTL locale the bidi algorithm reorders the punctuation around
            those values, so it must not inherit page direction. The physical
            padding below is deliberate for the same reason: the indentation
            belongs to the code, not to the reading direction.
          */}
          <dl dir="ltr" className="mt-3 space-y-1 font-mono text-xs">
            <div>settleDispute(</div>
            <div className="pl-4">escrowId: {instructions.escrow_id}</div>
            <div className="pl-4">
              providerAmount: {instructions.provider_amount_base_units}
            </div>
            <div className="pl-4">buyerAmount: {instructions.buyer_amount_base_units}</div>
            <div>)</div>
            <div className="pt-2">contract: {instructions.escrow_contract}</div>
            <div>chainId: {instructions.chain_id}</div>
          </dl>
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          <div>
            <label className="text-xs text-[var(--text-muted)]">
              {t("providerShare", { currency: row.currency })}
            </label>
            <input
              type="text"
              inputMode="decimal"
              value={providerAmount}
              onChange={(e) => setProviderAmount(e.target.value)}
              className={`${controlClass} mt-1.5 font-mono`}
              placeholder="0.000000"
            />
            {buyerShown !== null ? (
              <p className="mt-1.5 text-xs text-[var(--text-muted)]">
                {t("buyerReceives", { amount: buyerShown, currency: row.currency })}
              </p>
            ) : null}
          </div>
          <div>
            <label className="text-xs text-[var(--text-muted)]">{t("reasoning")}</label>
            <textarea
              value={reasoning}
              rows={4}
              maxLength={4000}
              onChange={(e) => setReasoning(e.target.value)}
              className={`${controlClass} mt-1.5 resize-y`}
            />
            <p className="mt-1.5 text-xs text-[var(--text-muted)]">{t("reasoningHint")}</p>
          </div>
          <Button
            onClick={decide}
            disabled={busy || !providerAmount.trim() || !reasoning.trim()}
          >
            {busy ? t("deciding") : t("decide")}
          </Button>
        </div>
      )}

      {error ? <p className="mt-3 text-sm text-danger-500">{error}</p> : null}
    </section>
  );
}
