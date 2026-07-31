"use client";

import { createAppKit } from "@reown/appkit/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { WagmiProvider } from "wagmi";

import { AuthProvider } from "@/components/auth/auth-provider";
import { siteConfig } from "@/lib/site";
import {
  defaultNetwork,
  networks,
  projectId,
  wagmiAdapter,
  wagmiConfig,
} from "@/lib/wagmi";

// Initialise AppKit once, at module load in this client boundary. Wallet-only:
// no email login, no social login, and Reown's own analytics are off, the site
// runs its own cookieless analytics and does not need a second tracker.
createAppKit({
  adapters: [wagmiAdapter],
  networks,
  defaultNetwork,
  projectId,
  metadata: {
    name: siteConfig.name,
    description: "The Autonomous Agent Commerce Hub",
    url: siteConfig.url,
    icons: [`${siteConfig.url}/icons/android-chrome-192x192.png`],
  },
  features: { analytics: false, email: false, socials: [] },
  themeMode: "dark",
  themeVariables: {
    "--w3m-accent": "#4b48e0",
    "--w3m-border-radius-master": "2px",
  },
});

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

  return (
    <WagmiProvider config={wagmiConfig}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    </WagmiProvider>
  );
}
