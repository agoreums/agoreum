"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { useAccount, useConnect, useSwitchChain } from "wagmi";

import { useAuth } from "@/components/auth/auth-provider";
import { defaultChain, walletConnectConfigured } from "@/lib/wagmi";

/** Shortens an address for display: 0x1234…abcd. */
export function truncateAddress(address: string): string {
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

const CONNECTOR_LABELS: Record<string, string> = {
  injected: "Browser Wallet",
  "io.metamask": "MetaMask",
  metaMask: "MetaMask",
  metaMaskSDK: "MetaMask",
  coinbaseWalletSDK: "Coinbase Wallet",
  coinbaseWallet: "Coinbase Wallet",
  walletConnect: "WalletConnect",
};

function connectorLabel(id: string, fallback: string): string {
  return CONNECTOR_LABELS[id] ?? fallback;
}

export function ConnectWalletButton() {
  const t = useTranslations("nav");
  const tAuth = useTranslations("auth");
  const { address, isConnected, chainId } = useAccount();
  const { connectors, connect, isPending: isConnecting } = useConnect();
  const { switchChain } = useSwitchChain();
  const { status, user, signIn, signOut, error, clearError } = useAuth();

  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  // Deduplicate: EIP-6963 discovery and the generic injected connector can both
  // surface the same physical wallet.
  const uniqueConnectors = connectors.filter(
    (connector, index, all) =>
      all.findIndex((c) => connectorLabel(c.id, c.name) === connectorLabel(connector.id, connector.name)) ===
      index,
  );

  const onWrongChain =
    isConnected && chainId !== undefined && chainId !== defaultChain.id;

  if (status === "authenticated" && user) {
    return (
      <div className="flex items-center gap-2">
        <span
          className="hidden rounded-lg border border-[var(--border-subtle)] px-3 py-2 font-mono text-xs text-[var(--text-secondary)] sm:inline-flex"
          title={user.primary_address}
        >
          {user.display_name ?? truncateAddress(user.primary_address)}
        </span>
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
    <>
      <button
        type="button"
        onClick={() => {
          clearError();
          setOpen(true);
        }}
        className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-500"
      >
        {t("connectWallet")}
      </button>

      <dialog
        ref={dialogRef}
        onClose={() => setOpen(false)}
        onClick={(e) => {
          if (e.target === dialogRef.current) setOpen(false);
        }}
        aria-labelledby="connect-title"
        className="w-[min(26rem,92vw)] rounded-[var(--radius-panel)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-0 text-[var(--text-primary)] backdrop:bg-black/60 backdrop:backdrop-blur-sm"
      >
        <div className="p-6">
          <h2 id="connect-title" className="text-lg font-semibold">
            {tAuth("connectTitle")}
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
            {tAuth("connectBody")}
          </p>

          <ul className="mt-6 space-y-2">
            {uniqueConnectors.map((connector) => (
              <li key={connector.uid}>
                <button
                  type="button"
                  disabled={isConnecting}
                  onClick={() => {
                    connect({ connector });
                    setOpen(false);
                  }}
                  className="flex w-full items-center justify-between rounded-xl border border-[var(--border-subtle)] px-4 py-3.5 text-left text-sm transition-colors hover:bg-[var(--surface-overlay)] disabled:opacity-60"
                >
                  <span>{connectorLabel(connector.id, connector.name)}</span>
                  <span aria-hidden="true" className="text-[var(--text-muted)]">
                    →
                  </span>
                </button>
              </li>
            ))}
          </ul>

          {!walletConnectConfigured ? (
            // Stated plainly rather than showing a button that cannot work.
            <p className="mt-4 text-xs leading-relaxed text-[var(--text-muted)]">
              {tAuth("walletConnectUnavailable")}
            </p>
          ) : null}

          <p className="mt-5 text-xs leading-relaxed text-[var(--text-muted)]">
            {tAuth("nonCustodialNotice")}
          </p>

          <button
            type="button"
            onClick={() => setOpen(false)}
            className="mt-5 w-full rounded-lg border border-[var(--border-subtle)] px-4 py-2.5 text-sm text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]"
          >
            {tAuth("cancel")}
          </button>
        </div>
      </dialog>
    </>
  );
}
