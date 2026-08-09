# Uptime worker

Watches `agoreum.xyz` from Cloudflare's cron, every minute, and reports to the
same Telegram channel the on-droplet monitor uses.

It exists because the on-droplet monitor cannot report that the droplet is gone:
it goes down with it. A reboot drill confirmed that, sending nothing during the
outage and reporting a problem only once it was already back.

## Two checks, deliberately

| Check | Interval | Role |
| --- | --- | --- |
| This Worker | every minute | primary |
| `.github/workflows/uptime.yml` | every five minutes, best effort | redundant secondary |

They share no infrastructure with each other or with the droplet, so a fault in
either scheduler still leaves the site watched. The GitHub schedule is kept
despite being unreliable: measured, its first scheduled run took about a hundred
minutes to appear and it has fired sparsely since, which is why it is the backup
rather than the primary.

## Behaviour

- Probes the public page and the API. The API must return live JSON with
  `status: ok`, not merely a 200, so that if edge caching is ever enabled the
  check does not quietly become a test of Cloudflare's cache.
- Alerts after two consecutive failures, roughly two minutes, so a single blip
  stays quiet.
- Alerts once, not every minute, and sends exactly one all-clear on recovery.
  The state lives in KV.
- No route and no `workers.dev` subdomain. The `fetch` handler exists so the
  check can be run on demand, and exposing it publicly would let a stranger make
  us send Telegram messages.

## Tests

```bash
node --test
```

Covers the transitions rather than the probes: below-threshold silence, alerting
once, not repeating, exactly one all-clear, and a cached HTML page being counted
as down rather than healthy.

## Token scope

`CLOUDFLARE_API_TOKEN` holds exactly two permission groups, both scoped to the
account:

- **Workers Scripts Write**, which covers deploying, setting cron triggers,
  managing the Worker's secrets, and reading logs with `wrangler tail`
- **Workers KV Storage Write**

That is the whole of what this Worker needs. The token previously carried 273
permission groups, effectively every account-scoped permission Cloudflare
offers, including billing, account settings, API token management, Registrar
domain administration and all of Zero Trust. None of it was used and all of it
was reachable, so it was narrowed to these two.

Two consequences worth knowing before you reach for it:

- **It cannot widen itself.** `Account API Tokens Write` is gone, so any future
  permission change has to be made from the Cloudflare dashboard.
- **It grants nothing at zone level.** No DNS, no zone settings, no firewall
  rules, no page rules. It can still enumerate the account's zones, which
  returns names and ids only; that is inherent to an account-scoped token rather
  than something these two permissions grant.

## Deploying

Credentials come from the repository root `.env`, as everything else here does.
Nothing is stored in this directory.

```bash
export CLOUDFLARE_API_TOKEN=...   # from .env
export CLOUDFLARE_ACCOUNT_ID=...  # from .env
npx wrangler deploy
```

Secrets are set once and live in Cloudflare, not in this repository:

```bash
npx wrangler secret bulk secrets.json   # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

Write that file outside the repository and delete it afterwards.

## Checking it is alive

```bash
npx wrangler tail agoreum-uptime --format json
npx wrangler kv key get --namespace-id <id> "uptime:state" --remote
```

The `--remote` flag matters. Without it wrangler reads local storage and reports
`Value not found` for a key that exists, which looks exactly like a Worker that
is not running.
