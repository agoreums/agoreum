"use client";

import { useAppKit } from "@reown/appkit/react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { useAccount, useSwitchChain } from "wagmi";

import { useAuth } from "@/components/auth/auth-provider";
import { warmWalletModal } from "@/lib/appkit";
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
  const [opening, setOpening] = useState(false);

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

  // `open()` resolves only once AppKit's modal UI has been imported, so on a cold
  // cache the tap is followed by a stretch of nothing at all. Warming on pointer
  // intent starts that import a beat before the click lands, and the pending label
  // covers the case where it is somehow still in flight, so the button is never
  // silently unresponsive.
  //
  // The button is deliberately not disabled while opening: a disabled control loses
  // focus and reads as broken rather than busy, and AppKit's `open()` is safe to
  // call twice.
  const openModal = () => {
    setOpening(true);
    void Promise.resolve(open()).finally(() => setOpening(false));
  };

  return (
    <button
      type="button"
      onPointerEnter={() => void warmWalletModal()}
      onPointerDown={() => void warmWalletModal()}
      onFocus={() => void warmWalletModal()}
      onClick={openModal}
      aria-busy={opening}
      className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-500"
    >
      {opening ? tAuth("connecting") : t("connectWallet")}
    </button>
  );
}
