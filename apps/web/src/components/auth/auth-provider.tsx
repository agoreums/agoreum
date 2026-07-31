"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useAccount, useDisconnect, useSignMessage } from "wagmi";

import { ApiError, authApi, type Tokens, type UserProfile } from "@/lib/api";
import {
  clearSession,
  isExpired,
  loadTokens,
  loadUser,
  millisecondsUntilRefresh,
  saveTokens,
  saveUser,
} from "@/lib/auth-storage";

export type AuthStatus =
  | "loading"
  | "unauthenticated"
  | "authenticating"
  | "authenticated";

type AuthContextValue = {
  status: AuthStatus;
  user: UserProfile | null;
  accessToken: string | null;
  error: string | null;
  signIn: () => Promise<void>;
  signOut: (allSessions?: boolean) => Promise<void>;
  clearError: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

/** Maps a wagmi connector id onto the backend's WalletProvider enum. */
function walletProviderFor(connectorId: string | undefined): string {
  switch (connectorId) {
    case "coinbaseWalletSDK":
    case "coinbaseWallet":
      return "coinbase";
    case "walletConnect":
      return "walletconnect";
    case "io.metamask":
    case "metaMask":
    case "metaMaskSDK":
      return "metamask";
    case "injected":
      return "injected";
    default:
      return "other";
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const { address, chainId, connector, isConnected } = useAccount();
  const { signMessageAsync } = useSignMessage();
  const { disconnect } = useDisconnect();

  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<UserProfile | null>(null);
  const [tokens, setTokens] = useState<Tokens | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const applySession = useCallback((next: Tokens, profile?: UserProfile) => {
    setTokens(next);
    saveTokens(next);
    if (profile) {
      setUser(profile);
      saveUser(profile);
    }
    setStatus("authenticated");
  }, []);

  const endSession = useCallback(() => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = null;
    setTokens(null);
    setUser(null);
    clearSession();
    setStatus("unauthenticated");
  }, []);

  // Restore a session from storage on first mount.
  //
  // Restoration is genuinely asynchronous: storage is unreadable during server
  // rendering, and a stored access token may need refreshing before it can be
  // trusted. Running it off the render path also avoids a hydration mismatch
  // between the server's "loading" output and whatever the browser has stored.
  useEffect(() => {
    let cancelled = false;

    async function restore() {
      const storedTokens = loadTokens();
      const storedUser = loadUser();

      if (!storedTokens || !storedUser) {
        if (!cancelled) setStatus("unauthenticated");
        return;
      }

      if (isExpired(storedTokens)) {
        // The access token is dead, but the refresh token may still be good.
        try {
          const fresh = await authApi.refresh(storedTokens.refresh_token);
          if (cancelled) return;
          setTokens(fresh);
          saveTokens(fresh);
          setUser(storedUser);
          setStatus("authenticated");
        } catch {
          if (cancelled) return;
          clearSession();
          setStatus("unauthenticated");
        }
        return;
      }

      if (cancelled) return;
      setTokens(storedTokens);
      setUser(storedUser);
      setStatus("authenticated");
    }

    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  // Refresh shortly before the access token expires, so a signed-in user is
  // never bounced mid-session.
  useEffect(() => {
    if (!tokens || status !== "authenticated") return;

    const delay = millisecondsUntilRefresh(tokens);
    refreshTimer.current = setTimeout(() => {
      authApi
        .refresh(tokens.refresh_token)
        .then((fresh) => {
          setTokens(fresh);
          saveTokens(fresh);
        })
        .catch(() => {
          // The refresh token was revoked or expired. The only correct response
          // is to end the session rather than pretend it is still valid.
          endSession();
        });
    }, delay);

    return () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [tokens, status, endSession]);

  // A signed-in session belongs to exactly one address. If the wallet switches
  // accounts or disconnects, the session no longer describes who is present and
  // must end, continuing to act as the previous account would be a real
  // authorisation flaw, not a cosmetic one.
  //
  // The wallet is an external system whose changes arrive outside React, so this
  // is legitimately effect-shaped. The teardown is deferred to a microtask so it
  // does not run as a synchronous cascade during the wallet's own state update.
  useEffect(() => {
    if (status !== "authenticated" || !user) return;

    const addressChanged =
      address !== undefined && address.toLowerCase() !== user.primary_address;

    if (!isConnected || addressChanged) {
      const timer = setTimeout(endSession, 0);
      return () => clearTimeout(timer);
    }
  }, [address, isConnected, status, user, endSession]);

  // The React Compiler declines to auto-memoize this function (async body with
  // branching error handling), so the manual useCallback is kept deliberately:
  // without it `signIn` changes identity every render, which would change the
  // context value every render and re-render every consumer.
  // eslint-disable-next-line react-hooks/preserve-manual-memoization
  const signIn = useCallback(async () => {
    if (!address || !chainId) {
      setError("Connect a wallet first.");
      return;
    }

    setStatus("authenticating");
    setError(null);

    try {
      const challenge = await authApi.requestNonce(address, chainId);
      if (!challenge.message) {
        throw new Error("The server did not return a message to sign.");
      }

      const signature = await signMessageAsync({ message: challenge.message });

      const result = await authApi.signIn({
        message: challenge.message,
        signature,
        nonce: challenge.nonce,
        wallet_provider: walletProviderFor(connector?.id),
      });

      applySession(result.tokens, result.user);
    } catch (err) {
      setStatus("unauthenticated");

      if (err instanceof ApiError) {
        setError(err.message);
      } else if (
        err instanceof Error &&
        /user rejected|denied|cancelled|canceled/i.test(err.message)
      ) {
        // A deliberate cancellation is not an error worth alarming anyone about.
        setError(null);
      } else {
        setError(
          err instanceof Error ? err.message : "Sign-in failed. Please try again.",
        );
      }
    }
  }, [address, chainId, connector?.id, signMessageAsync, applySession]);

  const signOut = useCallback(
    async (allSessions = false) => {
      if (tokens) {
        try {
          await authApi.logout(
            tokens.access_token,
            tokens.refresh_token,
            allSessions,
          );
        } catch {
          // Even if the server call fails, the local session must still end.
        }
      }
      endSession();
      disconnect();
    },
    [tokens, endSession, disconnect],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      accessToken: tokens?.access_token ?? null,
      error,
      signIn,
      signOut,
      clearError: () => setError(null),
    }),
    [status, user, tokens, error, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside <AuthProvider>.");
  }
  return context;
}
