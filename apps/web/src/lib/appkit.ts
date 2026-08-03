"use client";

import { ApiController } from "@reown/appkit-controllers";
import type { CreateAppKit } from "@reown/appkit/react";

import { siteConfig } from "@/lib/site";
import { defaultNetwork, networks, projectId, wagmiAdapter } from "@/lib/wagmi";

/**
 * AppKit configuration.
 *
 * Exported as a value rather than applied here: the `createAppKit()` call lives in
 * `providers.tsx`, beside the component that needs it. Putting the call in this
 * module instead looks tidier and does not work, Turbopack splits a module into
 * fragments and drops the one holding a top-level call whose result nothing
 * imports, which leaves AppKit silently uninitialised and the wallet modal unable
 * to open. Configuration travels; the side effect stays put.
 *
 * Wallet-only, and now actually wallet-only. Reown's own analytics stay off
 * because the site runs its own cookieless analytics and does not need a second
 * tracker.
 *
 * The extra `false`s are load-bearing, not defensive noise. AppKit builds the view
 * set it will import from the project config it fetches from Reown, and the
 * dashboard for this project reports social login, swaps, onramp and activity as
 * enabled. It does not follow that they win. `ConfigUtil.processFeature` only
 * prefers the remote answer when that feature arrives carrying a non-null `config`
 * payload; when `config` is `null`, which is what every feature in this project's
 * response has, it calls `processFallbackFeature` and the local value decides. So
 * naming them here is what actually turns them off, and leaving them unset is what
 * left them on: an unset feature falls through to AppKit's enabled-by-default.
 *
 * That matters because `loadModalComponents` awaits every enabled view before the
 * modal renders anything, so each one left on is a chunk sitting between the tap
 * and the wallet list. Note the key for activity is `history`, not `activity`.
 *
 * `--w3m-font-family` is not cosmetic. Without a custom font family AppKit injects
 * eight `<link rel="preload">` tags pointing at fonts.reown.com and downloads its
 * KHTeka faces in both woff2 *and* woff, measured at 136 KB over seven requests to
 * a third-party host, all of it on the critical path between the connect tap and
 * the modal painting. Setting the variable makes AppKit skip those preloads
 * entirely and render in the site's own already-loaded Inter, which is both faster
 * and visually consistent with the rest of Agoreum.
 */
export const appKitConfig: CreateAppKit = {
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
  features: {
    analytics: false,
    email: false,
    socials: [],
    swaps: false,
    onramp: false,
    history: false,
  },
  themeMode: "dark",
  themeVariables: {
    "--w3m-accent": "#4b48e0",
    "--w3m-font-family": "var(--font-inter), ui-sans-serif, system-ui, sans-serif",
    "--w3m-border-radius-master": "2px",
  },
};

let warming: Promise<unknown> | null = null;

/**
 * Pull the wallet modal's UI into the module registry before the user asks for it.
 *
 * `appKit.open()` awaits `injectModalUi()`, which lazily `import()`s the whole
 * scaffold-ui bundle. Profiled on a Pixel 7 over 4G that is a dozen chunk requests
 * happening *after* the tap, so the button looks dead for seconds. Worse, AppKit
 * `Promise.all`s every enabled feature view before it will show anything, so the
 * connect screen waits on swap, onramp, and activity UI that a visitor choosing a
 * wallet never sees.
 *
 * The list below mirrors exactly what `loadModalComponents` imports for the
 * feature set configured above: the modal shell and the two views AppKit enables
 * by default. Everything else is switched off in `appKitConfig`, so prefetching it
 * would download a chunk the modal never asks for. If a feature is turned back on
 * there, add it here too, otherwise it lands straight back on the critical path.
 *
 * Importing the modules directly, rather than driving AppKit, is deliberate.
 * `injectModalUi` latches a module-level `isInitialized` flag and reads a feature
 * set that `initialize()` fetches over the network, so triggering it early would
 * pin the modal to whatever had arrived by then. It is also unusable as a warm-up
 * in practice: `initialize()` awaits `syncExistingConnection()`, which on a first
 * visit with no prior wallet does not settle promptly, so anything gated on
 * `ready()` never runs for exactly the visitor who needs it most. A bare `import()`
 * has neither problem. It only populates the registry, and every specifier here is
 * one AppKit itself will ask for, so `open()` gets cache hits and nothing else
 * about its behaviour changes.
 *
 * The `ApiController.prefetch()` call is the other half, and on a slow connection
 * the larger half. `ModalController.open()` starts with `await
 * ApiController.prefetch()`, which fetches the featured and recommended wallet
 * lists, the connector and network images, and the wallet ranks. AppKit only
 * prefetches these during `initialize()` in headless mode, which this app is not,
 * so for us that whole round trip lands on the tap. `prefetch` memoises each fetch
 * by key in `ApiController.state.promises`, so calling it early means the `await`
 * inside `open()` resolves against promises that already settled. It has to run
 * after `createAppKit`, which it does: that call is at module scope in
 * `providers.tsx` and this runs from an effect.
 *
 * Idempotent: the promise is cached, so the idle pass and the pointer-intent pass
 * collapse into one load. A failure clears the cache so a later attempt can retry,
 * and never breaks the real connect flow, `open()` still loads its own chunks.
 */
export function warmWalletModal(): Promise<unknown> {
  warming ??= Promise.all([
    ApiController.prefetch(),
    import("@reown/appkit-scaffold-ui"),
    import("@reown/appkit-scaffold-ui/w3m-modal"),
    import("@reown/appkit-scaffold-ui/send"),
    import("@reown/appkit-scaffold-ui/receive"),
  ]).catch(() => {
    warming = null;
  });
  return warming ?? Promise.resolve();
}
