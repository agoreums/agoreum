"use client";

import { useAppKit } from "@reown/appkit/react";
import { useTranslations } from "next-intl";
import { useAccount, useSwitchChain } from "wagmi";

import { useAuth } from "@/components/auth/auth-provider";
import { defaultChain } from "@/lib/wagmi";

/** Shortens an address for display: 0x1234…abcd. */
export function truncateAddress(address: string): string {
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

/**
 * Wallet connect / sign-in control.
 *
 * Wallet selection (MetaMask, Coinbase, WalletConnect) is delegated to the Reown
 * AppKit modal, opened with `open()`. Once a wallet is connected, the button
 * carries the app's own flow: switch to the right network if needed, then a SIWE
 * sign-in against the backend, then the signed-in identity. AppKit handles the
 * connection; Agoreum still owns the session.
 */
export function ConnectWalletButton() {
  const t = useTranslations("nav");
  const tAuth = useTranslations("auth");
  const { open } = useAppKit();
  const { address, isConnected, chainId } = useAccount();
  const { switchChain } = useSwitchChain();
  const { status, user, signIn, signOut, error } = useAuth();

  const onWrongChain =
    isConnected && chainId !== undefined && chainId !== defaultChain.id;

  if (status === "authenticated" && user) {
    return (
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => open({ view: "Account" })}
          className="hidden rounded-lg border border-[var(--border-subtle)] px-3 py-2 font-mono text-xs text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)] sm:inline-flex"
          title={user.primary_address}
        >
          {user.display_name ?? truncateAddress(user.primary_address)}
        </button>
        <button
          type="button"
          onClick={() => void signOut()}
          className="rounded-lg px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]"
        >
          {tAuth("signOut")}
        </button>
      </div>
    );
  }

  if (isConnected && address) {
    return (
      <div className="flex items-center gap-2">
        {onWrongChain ? (
          <button
            type="button"
            onClick={() => switchChain({ chainId: defaultChain.id })}
            className="rounded-lg bg-warning-500/15 px-3 py-2 text-sm font-medium text-warning-500 transition-colors hover:bg-warning-500/25"
          >
            {tAuth("switchNetwork", { network: defaultChain.name })}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => void signIn()}
            disabled={status === "authenticating"}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-500 disabled:opacity-60"
          >
            {status === "authenticating" ? tAuth("signing") : tAuth("signIn")}
          </button>
        )}
        {error ? (
          <p role="alert" className="text-xs text-danger-500">
            {error}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => open()}
      className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-500"
    >
      {t("connectWallet")}
    </button>
  );
}
