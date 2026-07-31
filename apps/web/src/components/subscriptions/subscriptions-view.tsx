"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { erc20Abi } from "viem";
import { useAccount, usePublicClient, useWriteContract } from "wagmi";

import { useAuth } from "@/components/auth/auth-provider";
import {
  ApiError,
  subscriptionsApi,
  type SubscriptionPayment,
  type SubscriptionPlan,
  type SubscriptionStatus,
} from "@/lib/api";
import subscriptionsAbi from "@/lib/subscriptions-abi";

type Step =
  | "idle"
  | "checking"
  | "approving"
  | "subscribing"
  | "confirming"
  | "done"
  | "error";

/**
 * Subscriptions: plans, the subscribe flow, current status, and payment history.
 *
 * The subscribe flow is non-custodial and explicit, approve the token, then call
 * subscribe from the buyer's own wallet. The platform only says what to send; it
 * never signs. Everything shown here is real: plans from the API, coverage and
 * receipts projected from confirmed on-chain payments.
 */
export function SubscriptionsView() {
  const t = useTranslations("subscriptions");
  const { status, accessToken } = useAuth();

  const [plans, setPlans] = useState<SubscriptionPlan[] | null>(null);
  const [mine, setMine] = useState<SubscriptionStatus[]>([]);
  const [payments, setPayments] = useState<SubscriptionPayment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const refresh = () => setReload((n) => n + 1);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const p = await subscriptionsApi.plans();
        if (cancelled) return;
        setPlans(p);
        if (status === "authenticated" && accessToken) {
          const [m, pay] = await Promise.all([
            subscriptionsApi.mine(accessToken),
            subscriptionsApi.payments(accessToken),
          ]);
          if (cancelled) return;
          setMine(m);
          setPayments(pay);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("loadFailed"));
          setPlans([]);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [status, accessToken, reload, t]);

  const activeByTier = new Map(mine.map((s) => [s.plan_id, s]));

  return (
    <div className="space-y-12">
      {error ? (
        <p className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-4 text-sm text-danger-500">
          {error}
        </p>
      ) : null}

      {plans === null ? (
        <p className="text-[var(--text-muted)]">{t("loading")}</p>
      ) : plans.length === 0 ? (
        <p className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center text-[var(--text-secondary)]">
          {t("noPlans")}
        </p>
      ) : (
        <section>
          <h2 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
            {t("plansTitle")}
          </h2>
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {plans.map((plan) => (
              <PlanCard
                key={plan.plan_id}
                plan={plan}
                current={activeByTier.get(plan.plan_id)}
                onChanged={refresh}
              />
            ))}
          </div>
        </section>
      )}

      {payments.length > 0 ? (
        <PaymentHistory payments={payments} />
      ) : null}
    </div>
  );
}

function PlanCard({
  plan,
  current,
  onChanged,
}: {
  plan: SubscriptionPlan;
  current: SubscriptionStatus | undefined;
  onChanged: () => void;
}) {
  const t = useTranslations("subscriptions");
  const { status } = useAuth();
  const { address, isConnected } = useAccount();
  const publicClient = usePublicClient();
  const { writeContractAsync } = useWriteContract();

  const [step, setStep] = useState<Step>("idle");
  const [err, setErr] = useState<string | null>(null);

  const intervalLabel = plan.interval === "yearly" ? t("perYear") : t("perMonth");
  const isActive = current && current.status !== "expired";

  const subscribe = useCallback(async () => {
    setErr(null);
    if (!isConnected || !address || !publicClient) {
      setErr(t("connectWallet"));
      return;
    }
    let instructions;
    try {
      instructions = await subscriptionsApi.instructions(plan.plan_id);
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 503 ? t("notAvailable") : t("subscribeFailed"));
      return;
    }

    const token = instructions.token_address as `0x${string}`;
    const contract = instructions.subscription_contract as `0x${string}`;
    const price = BigInt(instructions.price_base_units);
    const maxPrice = BigInt(instructions.max_price_base_units);

    try {
      setStep("checking");
      const allowance = await publicClient.readContract({
        address: token,
        abi: erc20Abi,
        functionName: "allowance",
        args: [address, contract],
      });
      if (allowance < price) {
        setStep("approving");
        const approveTx = await writeContractAsync({
          address: token,
          abi: erc20Abi,
          functionName: "approve",
          args: [contract, price],
        });
        await publicClient.waitForTransactionReceipt({ hash: approveTx });
      }

      setStep("subscribing");
      const tx = await writeContractAsync({
        address: contract,
        abi: subscriptionsAbi,
        functionName: "subscribe",
        args: [BigInt(plan.plan_id), maxPrice],
      });

      setStep("confirming");
      const receipt = await publicClient.waitForTransactionReceipt({ hash: tx });
      if (receipt.status !== "success") {
        setStep("error");
        setErr(t("errorReverted"));
        return;
      }
      setStep("done");
      // The indexer needs a moment to see the confirmed event; refresh shortly.
      setTimeout(onChanged, 4000);
    } catch (e) {
      const message = e instanceof Error ? e.message : "";
      if (/user rejected|denied|cancell?ed/i.test(message)) {
        setStep("idle");
        return;
      }
      setStep("error");
      setErr(message || t("subscribeFailed"));
    }
  }, [address, isConnected, publicClient, plan.plan_id, writeContractAsync, onChanged, t]);

  const busy = ["checking", "approving", "subscribing", "confirming"].includes(step);
  const stepLabel: Record<string, string> = {
    checking: t("stepChecking"),
    approving: t("stepApproving"),
    subscribing: t("stepSubscribing"),
    confirming: t("stepConfirming"),
  };

  return (
    <div className="flex h-full flex-col rounded-[var(--radius-panel)] border border-[var(--border-subtle)] p-6">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
          {plan.name}
        </h3>
        {isActive ? (
          <span className="rounded-full border border-success-500/40 px-2.5 py-0.5 text-xs font-medium text-success-500">
            {current!.status === "cancelled" ? t("statusCancelled") : t("statusActive")}
          </span>
        ) : null}
      </div>

      {plan.description ? (
        <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
          {plan.description}
        </p>
      ) : null}

      <p className="mt-4">
        <span className="text-[length:var(--text-h2)] font-semibold tracking-[var(--text-h2--letter-spacing)]">
          {plan.price} {plan.token_symbol}
        </span>
        <span className="text-sm text-[var(--text-muted)]"> {intervalLabel}</span>
      </p>

      {isActive ? (
        <p className="mt-3 text-xs text-[var(--text-muted)]">
          {current!.status === "cancelled"
            ? t("endsOn", { when: new Date(current!.current_period_end).toLocaleDateString() })
            : t("renewsOn", { when: new Date(current!.current_period_end).toLocaleDateString() })}
        </p>
      ) : null}

      <div className="mt-auto pt-6">
        {status !== "authenticated" ? (
          <p className="text-sm text-[var(--text-muted)]">{t("signInRequired")}</p>
        ) : (
          <>
            <button
              type="button"
              onClick={subscribe}
              disabled={busy}
              className="inline-flex w-full items-center justify-center rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-500 disabled:opacity-60"
            >
              {busy ? stepLabel[step] : isActive ? t("renew") : t("subscribe")}
            </button>
            {step === "done" ? (
              <p className="mt-2 text-center text-xs text-success-500">{t("stepDone")}</p>
            ) : null}
            {err ? <p className="mt-2 text-center text-xs text-danger-500">{err}</p> : null}
          </>
        )}
      </div>
    </div>
  );
}

function PaymentHistory({ payments }: { payments: SubscriptionPayment[] }) {
  const t = useTranslations("subscriptions");
  return (
    <section>
      <h2 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
        {t("historyTitle")}
      </h2>
      <ul className="mt-4 divide-y divide-[var(--border-subtle)] rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
        {payments.map((p) => (
          <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3.5">
            <span className="text-sm text-[var(--text-secondary)]">
              {t("paidOn", { when: new Date(p.created_at).toLocaleDateString() })}
            </span>
            <span className="font-mono text-sm text-[var(--text-primary)]">
              {p.amount} {p.token_symbol}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
