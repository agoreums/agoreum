import { base, baseSepolia } from "wagmi/chains";
import { createConfig, http } from "wagmi";
import { coinbaseWallet, injected, walletConnect } from "wagmi/connectors";

import { siteConfig } from "@/lib/site";

/**
 * Wallet connection configuration.
 *
 * Base only for now. `chains` is a tuple so adding a network is a one-line change
 * here rather than a redesign — nothing else in the app hardcodes a chain id.
 */
const walletConnectProjectId =
  process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID ?? "";

/**
 * WalletConnect refuses to initialise without a project id and throws at module
 * load. Rather than crashing the whole app, the connector is omitted and the UI
 * reports WalletConnect as unavailable — an honest degradation instead of a
 * button that cannot work.
 */
export const walletConnectConfigured = walletConnectProjectId.length > 0;

const chains = [base, baseSepolia] as const;

export const config = createConfig({
  chains,
  connectors: [
    // MetaMask and any other EIP-6963 browser extension wallet.
    injected({ shimDisconnect: true }),
    coinbaseWallet({
      appName: siteConfig.name,
      appLogoUrl: `${siteConfig.url}/icons/android-chrome-192x192.png`,
      // "all" enables Coinbase Smart Wallet as well as the extension. Smart
      // wallets sign via EIP-1271, which the backend verifies when an RPC
      // provider is configured.
      preference: "all",
    }),
    ...(walletConnectConfigured
      ? [
          walletConnect({
            projectId: walletConnectProjectId,
            showQrModal: true,
            metadata: {
              name: siteConfig.name,
              description: "The Autonomous Agent Commerce Hub",
              url: siteConfig.url,
              icons: [`${siteConfig.url}/icons/android-chrome-192x192.png`],
            },
          }),
        ]
      : []),
  ],
  transports: {
    // Public RPC by default. A dedicated Alchemy endpoint is used when supplied,
    // which matters for rate limits once there is real traffic.
    [base.id]: http(process.env.NEXT_PUBLIC_BASE_RPC_URL || undefined),
    [baseSepolia.id]: http(
      process.env.NEXT_PUBLIC_BASE_SEPOLIA_RPC_URL || undefined,
    ),
  },
  ssr: true,
});

export const defaultChain = base;

declare module "wagmi" {
  interface Register {
    config: typeof config;
  }
}
