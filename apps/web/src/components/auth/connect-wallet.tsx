"use client";

import { useAppKit } from "@reown/appkit/react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAccount, useSwitchChain } from "wagmi";

import { useAuth } from "@/components/auth/auth-provider";
import {
  WALLET_MODAL_DEADLINE_MS,
  clearWalletModalFetchCache,
  subscribeWalletModalOpen,
  warmWalletModal,
} from "@/lib/appkit";
import { defaultChain } from "@/lib/wagmi";

/** Shortens an address for display: 0x1234…abcd. */
export function truncateAddress(address: string): string {
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

/**
 * Shown when the wallet modal has not appeared within the deadline.
 *
 * A toast rather than something in the header, because the header on a phone has
 * no room for an explanation and this has to be readable exactly where the
 * problem shows up. It is `role="status"` with a polite live region so the
 * message is announced rather than only drawn.
 *
 * Anchored under the header rather than at the bottom of the viewport. The cookie
 * consent banner is `fixed bottom-0 z-50`, so a bottom-anchored toast would cover
 * it for precisely the first-time visitor this is most likely to reach. Sitting
 * below the header also puts the message next to the button it is about.
 */
function SlowOpenNotice({
  message,
  retryLabel,
  dismissLabel,
  onRetry,
  onDismiss,
}: {
  message: string;
  retryLabel: string;
  dismissLabel: string;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-x-4 top-20 z-[60] mx-auto flex max-w-md items-center gap-3 rounded-xl border border-[var(--border-strong)] bg-[var(--surface-overlay)] px-4 py-3 shadow-[var(--shadow-lifted)]"
    >
      <p className="flex-1 text-sm leading-snug text-[var(--text-secondary)]">
        {message}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="shrink-0 rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-500"
      >
        {retryLabel}
      </button>
      <button
        type="button"
        onClick={onDismiss}
        aria-label={dismissLabel}
        className="shrink-0 rounded-lg px-2 py-1.5 text-sm text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)]"
      >
        &times;
      </button>
    </div>
  );
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
  const [slow, setSlow] = useState(false);
  const deadline = useRef<ReturnType<typeof setTimeout> | null>(null);

  // `open()` is never abandoned, only raced. AppKit owns the modal, so cancelling
  // its promise is not ours to do and would not help: the work is a fetch with no
  // AbortSignal behind it. The deadline only decides when to *say* something.
  //
  // What clears the notice is AppKit's modal state below, not this promise
  // settling. That distinction is the whole fix: `open()` can resolve while the
  // modal never becomes visible, and an earlier version cleared the deadline in a
  // `finally`, so those runs showed no modal *and* no notice, which is precisely
  // the dead end this exists to prevent. Measured at 2 of 8 taps against production.
  // Settling the promise now only stops the button reading as busy.
  const startOpen = useCallback(() => {
    if (deadline.current) clearTimeout(deadline.current);
    setOpening(true);
    setSlow(false);

    deadline.current = setTimeout(() => setSlow(true), WALLET_MODAL_DEADLINE_MS);

    void Promise.resolve(open()).finally(() => setOpening(false));
  }, [open]);

  // Success is taken from AppKit's modal state, not from the promise, and it is
  // taken through a subscription because the modal is an external system. Clearing
  // on the open edge rather than deriving from `!modalOpen` matters: a derived
  // notice would spring back the moment the visitor dismissed a modal that had
  // opened late, because `slow` would still be set from that attempt.
  useEffect(
    () =>
      subscribeWalletModalOpen((isOpen) => {
        if (!isOpen) return;
        if (deadline.current) clearTimeout(deadline.current);
        deadline.current = null;
        setOpening(false);
        setSlow(false);
      }),
    [],
  );

  // Retrying has to drop Reown's memoised fetches first, otherwise the second
  // attempt just awaits the same stuck promise the first one is already stuck on.
  const retryOpen = useCallback(() => {
    clearWalletModalFetchCache();
    startOpen();
  }, [startOpen]);

  useEffect(
    () => () => {
      if (deadline.current) clearTimeout(deadline.current);
    },
    [],
  );

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

  // The button is deliberately not disabled while opening: a disabled control
  // loses focus and reads as broken rather than busy, and AppKit's `open()` is
  // safe to call twice.
  return (
    <>
      <button
        type="button"
        onPointerEnter={() => void warmWalletModal()}
        onPointerDown={() => void warmWalletModal()}
        onFocus={() => void warmWalletModal()}
        onClick={startOpen}
        aria-busy={opening}
        className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-500"
      >
        {opening ? tAuth("connecting") : t("connectWallet")}
      </button>

      {slow ? (
        <SlowOpenNotice
          message={tAuth("slowOpening")}
          retryLabel={tAuth("retry")}
          dismissLabel={tAuth("dismiss")}
          onRetry={retryOpen}
          onDismiss={() => setSlow(false)}
        />
      ) : null}
    </>
  );
}
