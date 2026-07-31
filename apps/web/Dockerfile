# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------- Dependencies
FROM node:22-bookworm-slim AS deps

WORKDIR /build

# Installed from the lockfile alone, so this layer is cached until dependencies
# actually change. `npm ci` fails rather than silently resolving a different
# tree, which is what makes the build reproducible.
# .npmrc carries legacy-peer-deps, needed so npm ci accepts the unused optional
# peer ranges AppKit's transitive deps declare (see apps/web/.npmrc).
COPY apps/web/package.json apps/web/package-lock.json apps/web/.npmrc ./
RUN npm ci --no-audit --no-fund

# --------------------------------------------------------------------- Build
FROM node:22-bookworm-slim AS builder

WORKDIR /build

ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /build/node_modules ./node_modules
COPY apps/web ./
# The ABI is generated into src/lib by scripts/sync_abi.py and committed, so no
# Solidity toolchain is needed here.

# NEXT_PUBLIC_* values are inlined into the client bundle at build time, so they
# must be present now rather than at container start. They are public by
# definition, an API URL and a WalletConnect project id, and no secret is
# passed in as a build argument.
ARG NEXT_PUBLIC_APP_URL
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_CHAIN_ID
ARG NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID
ARG NEXT_PUBLIC_BASE_RPC_URL
ARG NEXT_PUBLIC_BASE_SEPOLIA_RPC_URL
ARG NEXT_PUBLIC_UMAMI_URL
ARG NEXT_PUBLIC_UMAMI_WEBSITE_ID

ENV NEXT_PUBLIC_APP_URL=$NEXT_PUBLIC_APP_URL \
    NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_CHAIN_ID=$NEXT_PUBLIC_CHAIN_ID \
    NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID=$NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID \
    NEXT_PUBLIC_BASE_RPC_URL=$NEXT_PUBLIC_BASE_RPC_URL \
    NEXT_PUBLIC_BASE_SEPOLIA_RPC_URL=$NEXT_PUBLIC_BASE_SEPOLIA_RPC_URL \
    NEXT_PUBLIC_UMAMI_URL=$NEXT_PUBLIC_UMAMI_URL \
    NEXT_PUBLIC_UMAMI_WEBSITE_ID=$NEXT_PUBLIC_UMAMI_WEBSITE_ID

RUN npm run build

# ------------------------------------------------------------------- Runtime
FROM node:22-bookworm-slim AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1001 nextjs \
    && useradd --system --uid 1001 --gid nextjs --no-create-home nextjs

WORKDIR /srv/app

# `output: "standalone"` emits a self-contained server with only the modules it
# actually imports, so the full node_modules tree never ships. Static assets and
# public files are copied alongside because the standalone bundle omits them by
# design.
COPY --from=builder --chown=nextjs:nextjs /build/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /build/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nextjs /build/public ./public

USER nextjs

EXPOSE 3000

# Reports the upstream API's reachability too, so an unhealthy API surfaces here
# rather than as a broken page.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:3000/api/health || exit 1

CMD ["node", "server.js"]
