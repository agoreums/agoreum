"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { useAccount, usePublicClient, useWriteContract } from "wagmi";

import { useAuth } from "@/components/auth/auth-provider";
import escrowAbi from "@/lib/escrow-abi";
import {
  ApiError,
  ordersApi,
  type SettlementAction,
  type SettlementOptions,
} from "@/lib/api";

/**
 * The exits from an escrow, as buttons.
 *
 * This exists because it did not, and that was the most serious defect found in
 * this product. The interface could fund an escrow and nothing else: `approve`
 * plus `createEscrow`, and no release, refund or dispute anywhere. The contract
 * enforced a buyer's right to reclaim their money after the delivery deadline
 * the entire time, correctly, and no buyer could have invoked it without reading
 * the ABI and hand-building a transaction.
 *
 * The contract being correct is exactly why nothing caught it. Only trying to
 * use the guarantee as a real user, during the refund rehearsal of 2026-08-22,
 * showed that it was theoretical.
 *
 * Unavailable actions are shown, not hidden, with the reason and the moment they
 * open. A refund that silently disappears from the interface until some unstated
 * condition is met is indistinguishable from one that does not exist, which is
 * the belief this whole component is here to correct.
 */
export function SettlementActions({ orderId }: { orderId: string }) {
  const t = useTranslations("settlement");
  const { accessToken } = useAuth();
  const { chainId, isConnected } = useAccount();
  const publicClient = usePublicClient();
  const { writeContractAsync } = useWriteContract();

  const [options, setOptions] = useState<SettlementOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<string | null>(null);
  const [sentTx, setSentTx] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  const load = useCallback(() => {
    if (!accessToken) return Promise.resolve();
    return ordersApi
      .settlementOptions(accessToken, orderId)
      .then((next) => {
        setOptions(next);
        setError(null);
      })
      .catch((err: unknown) => {
        // A 409 means no escrow is configured in this environment. That is not
        // an error worth shouting about on an order page.
        if (!(err instanceof ApiError && err.status === 409)) {
          setError(err instanceof ApiError ? err.message : t("errors.loadFailed"));
        }
      })
      .finally(() => setLoading(false));
  }, [accessToken, orderId, t]);

  useEffect(() => {
    let cancelled = false;
    void load().then(() => {
      if (cancelled) return;
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const send = useCallback(
    async (action: SettlementAction) => {
      if (!publicClient || !options) return;
      setError(null);
      setSentTx(null);
      setPending(action.action);
      try {
        const hash = await writeContractAsync({
          address: options.escrow_contract as `0x${string}`,
          abi: escrowAbi,
          functionName: action.action,
          args:
            action.action === "dispute"
              ? [options.escrow_id as `0x${string}`, reason]
              : [options.escrow_id as `0x${string}`],
        });
        setSentTx(hash);
        const receipt = await publicClient.waitForTransactionReceipt({ hash });
        if (receipt.status !== "success") {
          // Saying the chain refused it beats showing success and letting the
          // user believe their money moved.
          setError(t("errors.reverted"));
          return;
        }
        await load();
      } catch (err) {
        const message = err instanceof Error ? err.message : "";
        if (/user rejected|denied|cancelled|canceled/i.test(message)) {
          setError(null);
        } else {
          setError(message || t("errors.failed"));
        }
      } finally {
        setPending(null);
      }
    },
    [publicClient, options, writeContractAsync, reason, load, t],
  );

  if (loading || !options) return null;

  const wrongChain = isConnected && chainId !== options.chain_id;

  return (
    <section className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-5">
      <h2 className="text-sm font-medium text-[var(--text-primary)]">
        {t("title")}
      </h2>
      <p className="mt-1.5 text-xs leading-relaxed text-[var(--text-muted)]">
        {options.note}
      </p>

      {options.contract_paused ? (
        <p className="mt-3 rounded-lg border border-warning-500/40 bg-warning-500/10 p-3 text-xs leading-relaxed text-warning-500">
          {t("paused")}
        </p>
      ) : null}

      <ul className="mt-4 space-y-3">
        {options.actions.map((action) => (
          <li
            key={action.action}
            className="rounded-xl border border-[var(--border-subtle)] p-4"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-[var(--text-primary)]">
                  {t(`actions.${action.action}`)}
                </p>
                <p className="mt-1 text-xs leading-relaxed text-[var(--text-muted)]">
                  {action.who}
                </p>
                {!action.available && action.reason ? (
                  <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                    {action.reason}
                  </p>
                ) : null}
                {!action.available && action.available_at ? (
                  <p className="mt-1 text-xs text-[var(--text-secondary)]">
                    {t("opensAt", {
                      when: new Date(action.available_at).toLocaleString(),
                    })}
                  </p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => void send(action)}
                disabled={
                  !action.available ||
                  pending !== null ||
                  wrongChain ||
                  (action.action === "dispute" && reason.trim().length < 10)
                }
                className="shrink-0 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-500 disabled:opacity-40"
              >
                {pending === action.action
                  ? t("sending")
                  : t(`do.${action.action}`)}
              </button>
            </div>

            {action.action === "dispute" && action.available ? (
              <div className="mt-3">
                <label
                  htmlFor="settlement-dispute-reason"
                  className="text-xs text-[var(--text-muted)]"
                >
                  {t("reasonLabel")}
                </label>
                <textarea
                  id="settlement-dispute-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={3}
                  maxLength={2000}
                  className="mt-1.5 w-full rounded-lg border border-[var(--border-subtle)] bg-transparent p-2.5 text-sm text-[var(--text-primary)]"
                />
                {/* The reason is written on chain and cannot be edited later,
                    which people should know before they send it. */}
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  {t("reasonIsPublic")}
                </p>
              </div>
            ) : null}

            {/* Published so the action can be taken without this interface at
                all. A guarantee that only works through our website is a
                guarantee that depends on us staying online. */}
            {action.calldata ? (
              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-[var(--text-muted)]">
                  {t("manual")}
                </summary>
                <dl className="mt-2 space-y-1 text-xs">
                  <div className="flex gap-2">
                    <dt className="text-[var(--text-muted)]">{t("contract")}</dt>
                    <dd className="min-w-0 break-all font-mono text-[var(--text-secondary)]">
                      {options.escrow_contract}
                    </dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-[var(--text-muted)]">{t("calldata")}</dt>
                    <dd className="min-w-0 break-all font-mono text-[var(--text-secondary)]">
                      {action.calldata}
                    </dd>
                  </div>
                </dl>
              </details>
            ) : null}
          </li>
        ))}
      </ul>

      {wrongChain ? (
        <p className="mt-3 text-xs text-warning-500">
          {t("wrongNetwork", { network: options.network_name })}
        </p>
      ) : null}

      {sentTx ? (
        <a
          href={`${options.explorer_url}/tx/${sentTx}`}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 inline-block font-mono text-xs text-brand-400 underline-offset-4 hover:underline"
        >
          {t("viewOnExplorer")}
        </a>
      ) : null}

      {error ? (
        <p role="alert" className="mt-3 text-xs leading-relaxed text-danger-500">
          {error}
        </p>
      ) : null}
    </section>
  );
}
