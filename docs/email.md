# Email

Transactional email runs through Resend, sending as `support@agoreum.xyz` from
the verified domain `agoreum.xyz`.

## Status: not enabled, and not yet ready to be

`EMAIL_SENDING_ENABLED` defaults to `False` in `apps/api/app/core/config.py`, and
`email_sending_available()` requires both that flag and a non-empty
`RESEND_API_KEY`. An unset value is off, and a malformed one fails at startup
rather than defaulting on. That gate is correct.

The more important fact is that **turning it on today would change nothing
observable**. `notify()` in `apps/api/app/modules/notifications/service.py` is the
only path to the Resend call, and it has no call sites anywhere in the codebase.
The infrastructure is built, the domain is genuinely verified, and no code sends
mail. Anyone reading `EMAIL_SENDING_ENABLED=false` and assuming email is merely
switched off has the wrong picture.

## DNS: authentication complete, inbound missing

Verified against Cloudflare and Google public resolvers rather than trusting the
provider dashboard, because what matters is what the world can actually see.

| Record | State |
| --- | --- |
| DKIM `resend._domainkey` | published, matches Resend |
| SPF `send.agoreum.xyz` | `v=spf1 include:amazonses.com ~all` |
| DMARC `_dmarc` | `v=DMARC1; p=none; rua=mailto:dmarc@agoreum.xyz; fo=1; adkim=r; aspf=r` |
| MX at the apex | **absent** |

`p=none` is monitoring only. It asks receivers to report on mail claiming to be
from this domain and changes nothing about delivery. Move to `p=quarantine` and
then `p=reject` once the aggregate reports arrive and look clean; going straight
to `reject` on an unmonitored domain is how legitimate mail disappears.

The missing MX means **`support@agoreum.xyz` cannot receive mail**. That address
is published on five public pages and named in `docs/security.md` as the
vulnerability disclosure channel, so security reports sent there currently
bounce. Cloudflare Email Routing is the straightforward fix: it provisions the MX
records and forwards to a real inbox. Its SPF entry sits at the apex and does not
disturb the `send.` subdomain Resend uses for outbound.

## Before enabling sending

1. **Wire up a caller.** Nothing invokes `notify()`. Until something does, the
   flag is inert.
2. **Verify recipient addresses.** `email_verified_at` is written in exactly one
   place, `apps/api/app/modules/auth/service.py`, where it is set to `None`. It is
   never set to a timestamp, there is no verification endpoint, and any address
   typed into `PATCH /auth/me` becomes a live delivery destination. Without
   verification, one account can point its profile email at a stranger and drive
   mail to them.
3. **Handle bounces and complaints.** Resend has no webhook configured and there
   is no suppression list. Sending from a cold domain with no bounce feedback is
   how a sending reputation is destroyed quietly.
4. **Add inbound for the support address**, as above.
5. **Turn off open and click tracking** for this domain. Both are currently on,
   with the tracking subdomain named `security`. Rewriting links in security mail
   through a redirector trains users to click redirectors in exactly the messages
   where they should not, and the open pixel is undisclosed tracking on a product
   that publishes a privacy page.
6. **Escape anything user-controlled** that reaches a subject or body. The Resend
   payload is currently text-only, so there is no injection today, but nothing
   sits between a caller-supplied string and the outbound message, and
   `display_name` accepts any 64 characters. The first HTML template or the first
   caller that interpolates an agent name creates the bug.

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
