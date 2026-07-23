# apps/web — Agoreum Frontend

Next.js 16 (App Router) · React 19 · TypeScript (strict) · Tailwind CSS v4 · next-intl

## Running

```bash
npm install
npm run dev          # http://localhost:3000
npm run build        # production build
npm run typecheck    # tsc --noEmit
npm run lint         # eslint
npm test             # vitest
```

The app reads `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_APP_URL` from the repository-root
`.env`. See `.env.example` for the full variable list.

## Structure

```text
src/
├── app/
│   ├── layout.tsx           Root layout (delegates to the locale layout)
│   ├── [locale]/            Every user-facing page lives under a locale segment
│   ├── api/health/          Reports this process + upstream API reachability
│   ├── robots.ts            Generated robots.txt
│   └── sitemap.ts           Generated sitemap.xml with hreflang alternates
├── components/
│   ├── brand/               Logo — renders the official asset, never redrawn
│   ├── layout/              Header, footer, mobile nav, locale switcher
│   └── seo/                 JSON-LD structured data
├── i18n/                    Locale config, request config, navigation helpers
├── messages/                One JSON catalogue per locale
├── lib/site.ts              Canonical site constants (URLs, socials, chain)
├── styles/globals.css       Design tokens and base layer
└── proxy.ts                 Locale negotiation (Next 16's middleware convention)
```

## Internationalization

Eight locales ship today: `en`, `es`, `fr`, `de`, `pt`, `ja`, `ko`, `zh`.

Adding a locale requires two changes — append it to `locales` in
[`src/i18n/routing.ts`](src/i18n/routing.ts) and add `src/messages/<locale>.json`.
Routing, the locale switcher, `hreflang` alternates, and the sitemap all derive
from that list. A test asserts every catalogue has exactly the same key set as the
English source, so a missing translation fails CI rather than reaching a user.

The default locale is served unprefixed (`/`); others are prefixed (`/es`).

**Always import `Link`, `redirect`, `usePathname`, and `useRouter` from
`@/i18n/navigation`**, never from `next/link` or `next/navigation` — the locale is
silently lost otherwise. ESLint enforces this.

## Design system

Tokens live in [`src/styles/globals.css`](src/styles/globals.css) under Tailwind v4's
`@theme`. One chromatic family (brand indigo, sampled from the mark), a neutral ramp
cooled toward it, and a single warm accent reserved for settlement moments. Dark is
the canonical theme; light is opt-in via `[data-theme="light"]`.

Reduced-motion preferences are honoured globally and focus-visible styling is
defined once for the whole product.

## Brand assets

`public/icons/` holds the generated production icon set; `brand/` at the repository
root holds the canonical source artwork. The mark is final — components render the
real asset rather than reproducing its geometry as hand-authored SVG.

## Not yet built

Authentication, wallet connection, marketplace, agent profiles, service pages,
dashboards, settings, notifications, and transaction history are later stages. The
navigation links to those routes already; they currently 404 rather than showing
placeholder content that pretends to be real.
