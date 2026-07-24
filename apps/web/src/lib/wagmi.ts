import { WagmiAdapter } from "@reown/appkit-adapter-wagmi";
import { base, baseSepolia, type AppKitNetwork } from "@reown/appkit/networks";

/**
 * Wallet configuration, built on Reown AppKit.
 *
 * AppKit replaces the hand-rolled connect dialog: it owns the wallet-selection
 * modal (MetaMask/injected, Coinbase, and the WalletConnect QR) and the network
 * switcher, while the rest of the app keeps using the standard wagmi hooks the
 * adapter exposes. The previous custom dialog drove WalletConnect through the
 * legacy `showQrModal` path, which silently no-opped under wagmi v3 — this is the
 * supported route rather than a patch around it.
 */
export const projectId = process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID ?? "";

// One value, `NEXT_PUBLIC_CHAIN_ID`, selects the chain — the backend's CHAIN_ID
// and this must agree. The configured network is listed first so AppKit opens on it.
const configuredChainId = Number(process.env.NEXT_PUBLIC_CHAIN_ID ?? String(base.id));

export const defaultNetwork: AppKitNetwork =
  configuredChainId === baseSepolia.id ? baseSepolia : base;

export const networks: [AppKitNetwork, ...AppKitNetwork[]] =
  configuredChainId === baseSepolia.id ? [baseSepolia, base] : [base, baseSepolia];

/** Retained for the wrong-network check in the connect button. */
export const defaultChain = {
  id: Number(defaultNetwork.id),
  name: defaultNetwork.name,
};

export const wagmiAdapter = new WagmiAdapter({
  networks,
  projectId,
  ssr: true,
});

export const wagmiConfig = wagmiAdapter.wagmiConfig;
