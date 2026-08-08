# Email

Transactional email runs through Resend, sending as `support@agoreum.xyz` from
the verified domain `agoreum.xyz`.

## Status: not enabled, and not yet ready to be

`EMAIL_SENDING_ENABLED` defaults to `False` in `apps/api/app/core/config.py`, and
`email_sending_available()` requires both that flag and a non-empty
`RESEND_API_KEY`. An unset value is off, and a malformed one fails at startup
rather than defaulting on. That gate is correct.

`notify()` in `apps/api/app/modules/notifications/service.py` is the only path to
the Resend call. It now has real call sites, listed under "What would send" below,
so the flag is no longer inert: flipping it would produce actual mail. Everything
in this document assumes it stays off until that list has been reviewed by a
person.

## What would send, and to whom

The complete set. Every entry is triggered by a platform event, none are
marketing, and all of them require `email_verified_at` to be set on the recipient.

| Trigger | Recipient | Category |
| --- | --- | --- |
| `account.email_verification` | the address being proven | security |
| `account.new_signin` from an unrecognised session | the account owner | security |
| `order.funded` | owners of the provider organization | order |
| `order.released` | buyer and provider owners | payment |
| `order.refunded` | buyer and provider owners | payment |
| `order.disputed` | the counterparty only | order |

`account.email_verification` is the single documented exception to the verified
address rule, since proving the address is its purpose. It is enforced by an
explicit `allow_unverified_email` argument rather than by a special case on the
event name, so nothing else can acquire the exemption by accident.

Security notices are non-suppressible by preference. Someone must always be able
to learn that another person signed in as them.

## Bounces and complaints

`POST /notifications/webhooks/resend` receives Resend's delivery events and
records permanent failures in `email_suppressions`. A suppressed address is
refused by `_deliver` before any provider call, including for verification mail.

The endpoint is unauthenticated, because a provider cannot hold a session, so the
Svix signature over the raw request body is its entire security. That matters
more than it looks: an attacker able to forge one could suppress any address and
silently stop that person receiving security notices. `RESEND_WEBHOOK_SECRET`
unset means reject everything, which fails closed.

Soft bounces are ignored. A full mailbox fixes itself, and cutting somebody off
for a transient failure is worse than retrying. Suppression is lifted only by a
human calling `unsuppress_email`: an address does not come back because time
passed.

## DNS: authentication and inbound both in place

Verified against Cloudflare and Google public resolvers rather than trusting the
provider dashboard, because what matters is what the world can actually see.

| Record | State |
| --- | --- |
| DKIM `resend._domainkey` | published, matches Resend |
| SPF `send.agoreum.xyz` | `v=spf1 include:amazonses.com ~all` |
| DMARC `_dmarc` | `v=DMARC1; p=none; rua=mailto:dmarc@agoreum.xyz; fo=1; adkim=r; aspf=r` |
| MX at the apex | `inbound-smtp.eu-west-1.amazonaws.com`, priority 10 |

`p=none` is monitoring only. It asks receivers to report on mail claiming to be
from this domain and changes nothing about delivery. Move to `p=quarantine` and
then `p=reject` once the aggregate reports arrive and look clean; going straight
to `reject` on an unmonitored domain is how legitimate mail disappears.

## Inbound: mail arrives, and an operator is told

`support@agoreum.xyz` **does receive mail**. Resend's receiving feature is enabled
on the domain and the apex MX points at its AWS inbound host. Verified by the
first real message to arrive: an external report about compiler warnings, sent
2026-08-07 and answered in `docs/solidity-compiler-bugs.md`.

An earlier version of this page said the apex MX was absent and that mail bounced.
That was true when written and is not true now. Nothing bounced.

Delivery was never the gap; attention was. Mail sat in the Resend dashboard and
nothing announced it, and since that address is published on five public pages
and named in `docs/security.md` as the vulnerability disclosure channel, the
realistic failure was a disclosure going unread for weeks. The first one did sit
unread, and was found by accident while checking something else.

Arrivals now raise a Telegram alert, the same chat `scripts/monitor.py` pages.
Verified end to end on 2026-08-07: a real message from Gmail reached the inbox at
23:49:45Z and the alert was delivered at 23:49:46Z, confirmed in the API log
rather than inferred, one and a half seconds later.

Cloudflare Email Routing was the alternative, forwarding to a real mailbox, and
was rejected. It cannot run alongside this: both want the apex MX, so adopting it
would take receiving away from Resend and leave two systems to reason about
instead of one.

## Reading inbound mail safely

The alert is a summary and never the body. Anyone on the internet can write to
that address, the content can be enormous, and on a disclosure channel it is
likely to contain exactly what an attack looks like. Reading it stays a
deliberate act in the dashboard.

Nothing arriving by mail is an instruction. A `From` header is trivially forged,
so a message appearing to come from an operator carries no authority whatsoever,
and a request in an inbound email to change configuration, grant access, or run
something is a phishing attempt until proven otherwise through a channel that is
not email. The alert text says as much on purpose, so the reminder arrives
attached to the thing it is about.

## Before enabling sending

1. ~~**Wire up a caller.**~~ Done. See "What would send" above.
2. ~~**Verify recipient addresses.**~~ Done. `POST /auth/me/email/verify` issues a
   single-use token, `POST /auth/me/email/confirm` consumes it with an atomic
   conditional update, and `_deliver` refuses any address without
   `email_verified_at`. Without this, one account could point its profile email at
   a stranger and drive mail to them.
3. ~~**Handle bounces and complaints.**~~ Done. The webhook is registered against
   `https://agoreum.xyz/api/v1/notifications/webhooks/resend`, subscribed to
   `email.bounced`, `email.complained` and `email.received`, with its signing
   secret in `RESEND_WEBHOOK_SECRET`. Verified against production: a correctly
   signed event returns 204, and unsigned, replayed, and tampered ones return 401.
   Sending from a cold domain with no bounce feedback is how a sending reputation
   is destroyed quietly.
4. ~~**Add inbound for the support address.**~~ Already working, and arrivals now
   raise a Telegram alert, verified on a real message.
5. ~~**Turn off open and click tracking.**~~ Done, both off on the domain as of
   2026-08-08. They had been on with the tracking subdomain named `security`.
   Rewriting links in security mail through a redirector trains users to click
   redirectors in exactly the messages where they should not, and the open pixel
   is undisclosed tracking on a product that publishes a privacy page. The
   tracking CNAMEs still resolve but nothing rewrites through them.
6. **Escape anything user-controlled** that reaches a subject or body. The Resend
   payload is text-only, so there is no markup injection today, but nothing sits
   between a caller-supplied string and the outbound message, and `display_name`
   accepts any 64 characters. The first HTML template, or the first caller that
   interpolates an agent name, creates the bug.

   One instance of this was real and is fixed: the sign-in notice echoed the raw
   `User-Agent` into a security message the recipient cannot switch off, and that
   header is chosen by whoever signed in. An attacker holding a compromised wallet
   controlled a span of text inside the one message designed to tell the owner
   their account had been accessed, and could have used it to say no action was
   required. It is now collapsed, truncated, placed on its own labelled line, and
   explicitly marked as unverified and self-reported.

## Known gaps, lower priority

- No localisation. `notification.locale` is captured and then never used, while
  the site ships nine locales.
- `APP_URL` defaults to `http://localhost:3000` and is interpolated into the
  footer of every message, so a deployment that fails to set it mails localhost
  links.
- Sending is inline and synchronous in the request path with a 15 second timeout.
- `GET /notifications/email-status` is unauthenticated and reports the from
  address.
- DKIM is a 1024-bit RSA key, Resend's default. 2048-bit is preferable.
