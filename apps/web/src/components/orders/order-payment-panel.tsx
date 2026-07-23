"use client";

import { useTranslations } from "next-intl";
import { useCallback, useState } from "react";
import { erc20Abi } from "viem";
import { useAccount, usePublicClient, useWriteContract } from "wagmi";

import { useAuth } from "@/components/auth/auth-provider";
import escrowAbi from "@/lib/escrow-abi";
import {
  ApiError,
  ordersApi,
  type ChainStatus,
  type PaymentInstructions,
} from "@/lib/api";

type Step =
  | "idle"
  | "creating-order"
  | "checking-allowance"
  | "approving"
  | "funding"
  | "confirming"
  | "done"
  | "error";

/**
 * Drives the buyer's wallet through funding an order.
 *
 * The platform never touches the money. This component reads the transaction
 * description from the API and hands it to the connected wallet, which builds,
 * signs and broadcasts it. Every signature prompt is the user's own.
 *
 * Funding is two on-chain calls, so the intermediate state is real and is shown
 * rather than hidden behind a single spinner: approve the token, then create the
 * escrow. If the second fails after the first succeeded, the allowance remains
 * and the retry skips straight to funding.
 */
export function OrderPaymentPanel({
  serviceId,
  chainStatus,
  priceLabel,
}: {
  serviceId: string;
  chainStatus: ChainStatus;
  priceLabel: string;
}) {
  const t = useTranslations("payment");
  const { status: authStatus, accessToken } = useAuth();
  const { address, chainId, isConnected } = useAccount();
  const publicClient = usePublicClient();
  const { writeContractAsync } = useWriteContract();

  const [step, setStep] = useState<Step>("idle");
  const [error, setError] = useState<string | null>(null);
  const [orderReference, setOrderReference] = useState<string | null>(null);
  const [fundingTx, setFundingTx] = useState<string | null>(null);

  const onWrongChain = isConnected && chainId !== chainStatus.chain_id;

  const pay = useCallback(async () => {
    if (!accessToken || !address || !publicClient) return;

    setError(null);
    setFundingTx(null);

    let instructions: PaymentInstructions;
    try {
      setStep("creating-order");
      const order = await ordersApi.create(accessToken, {
        service_id: serviceId,
        quantity: 1,
      });
      setOrderReference(order.reference);
      instructions = await ordersApi.paymentInstructions(accessToken, order.id);
    } catch (err) {
      setStep("error");
      setError(
        err instanceof ApiError ? err.message : t("errors.orderFailed"),
      );
      return;
    }

    const amount = BigInt(instructions.amount_base_units);
    const token = instructions.token_address as `0x${string}`;
    const escrow = instructions.escrow_contract as `0x${string}`;

    try {
      // Only approve when the existing allowance is insufficient. Re-approving
      // needlessly costs the user gas and an extra signature prompt.
      setStep("checking-allowance");
      const allowance = await publicClient.readContract({
        address: token,
        abi: erc20Abi,
        functionName: "allowance",
        args: [address, escrow],
      });

      if (allowance < amount) {
        setStep("approving");
        const approveTx = await writeContractAsync({
          address: token,
          abi: erc20Abi,
          functionName: "approve",
          // Approving exactly what is needed rather than an unlimited
          // allowance: if this contract is ever compromised, the exposure is
          // one order, not the user's entire balance.
          args: [escrow, amount],
        });
        await publicClient.waitForTransactionReceipt({ hash: approveTx });
      }

      setStep("funding");
      const fundTx = await writeContractAsync({
        address: escrow,
        abi: escrowAbi,
        functionName: "createEscrow",
        args: [
          instructions.escrow_id as `0x${string}`,
          instructions.provider_address as `0x${string}`,
          token,
          amount,
          BigInt(instructions.delivery_window_seconds),
          BigInt(instructions.auto_release_window_seconds),
        ],
      });
      setFundingTx(fundTx);

      setStep("confirming");
      const receipt = await publicClient.waitForTransactionReceipt({
        hash: fundTx,
        confirmations: chainStatus.confirmations_required,
      });

      if (receipt.status !== "success") {
        // The chain rejected it. Saying so plainly beats showing success and
        // letting the order sit unfunded.
        setStep("error");
        setError(t("errors.reverted"));
        return;
      }

      setStep("done");
    } catch (err) {
      setStep("error");
      const message = err instanceof Error ? err.message : "";
      if (/user rejected|denied|cancelled|canceled/i.test(message)) {
        setError(null);
        setStep("idle");
        return;
      }
      setError(message || t("errors.paymentFailed"));
    }
  }, [
    accessToken, address, publicClient, serviceId, writeContractAsync,
    chainStatus.confirmations_required, t,
  ]);

  // --- States where paying is impossible, each said plainly ----------------

  if (!chainStatus.escrow_configured) {
    return (
      <Notice title={t("unavailable.title")} body={t("unavailable.noContract")} />
    );
  }

  if (!chainStatus.rpc_reachable) {
    return (
      <Notice title={t("unavailable.title")} body={t("unavailable.noRpc")} />
    );
  }

  if (authStatus !== "authenticated") {
    return <Notice title={t("signInRequired.title")} body={t("signInRequired.body")} />;
  }

  if (onWrongChain) {
    return (
      <Notice
        title={t("wrongNetwork.title")}
        body={t("wrongNetwork.body", { network: chainStatus.network_name })}
      />
    );
  }

  if (step === "done") {
    return (
      <div className="rounded-xl border border-success-600/40 bg-success-600/10 p-4">
        <p className="text-sm font-medium text-success-500">{t("funded.title")}</p>
        <p className="mt-1.5 text-xs leading-relaxed text-[var(--text-secondary)]">
          {t("funded.body", { reference: orderReference ?? "" })}
        </p>
        {fundingTx ? (
          <a
            href={`${chainStatus.explorer_url}/tx/${fundingTx}`}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-block font-mono text-xs text-brand-400 underline-offset-4 hover:underline"
          >
            {t("viewOnExplorer")}
          </a>
        ) : null}
      </div>
    );
  }

  const busy = step !== "idle" && step !== "error";

  return (
    <div>
      <button
        type="button"
        onClick={() => void pay()}
        disabled={busy}
        className="w-full rounded-xl bg-brand-600 px-5 py-3.5 text-sm font-medium text-white transition-colors hover:bg-brand-500 disabled:opacity-60"
      >
        {busy ? t(`steps.${step}`) : t("payAction", { price: priceLabel })}
      </button>

      {/* The two-transaction shape is stated up front so the second wallet
          prompt is expected rather than alarming. */}
      <p className="mt-3 text-xs leading-relaxed text-[var(--text-muted)]">
        {t("twoStepNotice", { network: chainStatus.network_name })}
      </p>

      {fundingTx && step === "confirming" ? (
        <p className="mt-2 text-xs text-[var(--text-muted)]">
          {t("waitingForConfirmations", {
            count: chainStatus.confirmations_required,
          })}
        </p>
      ) : null}

      {error ? (
        <p role="alert" className="mt-3 text-xs leading-relaxed text-danger-500">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function Notice({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl border border-dashed border-[var(--border-subtle)] p-4">
      <p className="text-sm font-medium text-[var(--text-primary)]">{title}</p>
      <p className="mt-1.5 text-xs leading-relaxed text-[var(--text-muted)]">
        {body}
      </p>
    </div>
  );
}
