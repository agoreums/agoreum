"use client";

import { createAppKit } from "@reown/appkit/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { WagmiProvider } from "wagmi";

import { AuthProvider } from "@/components/auth/auth-provider";
import { appKitConfig, warmWalletModal } from "@/lib/appkit";
import { wagmiConfig } from "@/lib/wagmi";

// Initialise AppKit once, at module load in this client boundary. This call has to
// live in a module the app definitely evaluates, see the note on `appKitConfig`:
// a top-level call whose result nothing imports can be dropped as dead code, and
// the failure is silent, the modal simply never opens.
createAppKit(appKitConfig);

/**
 * Client-side provider stack.
 *
 * The QueryClient is created inside state rather than at module scope so that a
 * server render never shares a cache between requests, that would leak one
 * user's data into another's page.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  // Warm the wallet modal once the browser has nothing better to do. The connect
  // tap otherwise pays for the modal's lazy chunks and its round trip to Reown
  // in full, which on a phone is seconds of a button that looks broken. Deferring
  // to idle keeps those bytes off the critical path for the initial render, and
  // the connect button warms on pointer intent too, so a fast tapper is covered
  // even if idle time never arrives.
  useEffect(() => {
    if (typeof window.requestIdleCallback === "function") {
      const handle = window.requestIdleCallback(() => void warmWalletModal(), {
        timeout: 4000,
      });
      return () => window.cancelIdleCallback?.(handle);
    }
    // Safari below 16.4 has no requestIdleCallback; a plain delay is enough to
    // stay behind hydration and the first paint.
    const timer = setTimeout(() => void warmWalletModal(), 2500);
    return () => clearTimeout(timer);
  }, []);

  return (
    <WagmiProvider config={wagmiConfig}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    </WagmiProvider>
  );
}
