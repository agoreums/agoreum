#!/usr/bin/env bash
#
# Restrict the origin's HTTP/HTTPS ports to Cloudflare's IP ranges.
#
# WHY
#   nginx now refuses to trust a client-supplied CF-Connecting-IP, so a forged
#   header is discarded. That is only half the problem. While 80 and 443 accept
#   connections from anywhere, an attacker who learns the droplet's address can
#   still bypass Cloudflare completely: no WAF, no bot rules, no edge rate
#   limiting, and the origin's own limits keyed on a peer address the attacker
#   controls the choice of by picking their source. Closing the ports to
#   everything except Cloudflare is what makes the edge non-optional.
#
# SAFETY
#   This script is built so a mistake cannot take the site down or lock you out.
#     - SSH is verified reachable in the ruleset *before* anything is removed,
#       and is never touched.
#     - New allow rules are added first. The permissive rule is deleted last, so
#       there is no instant where 443 is closed to Cloudflare.
#     - It refuses to run if the fetched range list is short or empty, because a
#       truncated list would wall off most of Cloudflare's edge.
#     - It prints the plan and does nothing unless you pass --apply.
#     - It writes a rollback script before changing anything.
#
#   Run it with a second SSH session already open. If anything goes wrong, run
#   the rollback path it prints. DigitalOcean's web console is the last resort
#   and works even with ufw misconfigured.
#
# USAGE
#   ./restrict_origin_to_cloudflare.sh            # show the plan, change nothing
#   ./restrict_origin_to_cloudflare.sh --apply    # make the change
set -euo pipefail

APPLY=false
[ "${1:-}" = "--apply" ] && APPLY=true

command -v ufw >/dev/null || { echo "ufw is not installed" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
curl -fsS --max-time 30 https://www.cloudflare.com/ips-v4 -o "$TMP/v4"
curl -fsS --max-time 30 https://www.cloudflare.com/ips-v6 -o "$TMP/v6"

V4=$(grep -c . "$TMP/v4" || true)
V6=$(grep -c . "$TMP/v6" || true)

# Cloudflare has published roughly 15 IPv4 and 7 IPv6 ranges for years. A much
# smaller list means a truncated download or an error page, and applying it
# would silently block most legitimate traffic. Refuse rather than guess.
if [ "$V4" -lt 10 ] || [ "$V6" -lt 5 ]; then
  echo "range list looks wrong (v4=$V4 v6=$V6), refusing to touch the firewall" >&2
  exit 1
fi

# SSH must already be permitted, by any of the spellings ufw accepts. Removing
# the open web rules cannot lock you out, but if SSH were somehow not allowed
# this script would be the moment you discovered it.
if ! ufw status | grep -qiE '(^|[[:space:]])(22/tcp|OpenSSH|22)([[:space:]]|$)'; then
  echo "no SSH allow rule found in ufw. Add one before running this:" >&2
  echo "    ufw allow OpenSSH" >&2
  exit 1
fi

echo "Cloudflare ranges: $V4 IPv4, $V6 IPv6"
echo
echo "Plan:"
echo "  1. allow 80,443/tcp from each Cloudflare range"
echo "  2. delete the blanket 'allow 80/tcp' and 'allow 443/tcp' rules"
echo "  3. leave SSH exactly as it is"
echo

ROLLBACK=/root/agoreum-ufw-rollback.sh

if [ "$APPLY" != true ]; then
  echo "Dry run. Nothing changed. Re-run with --apply to make it so."
  exit 0
fi

# Capture the current state first, so there is always a way back.
{
  echo "#!/usr/bin/env bash"
  echo "# Restores the permissive web rules. Generated $(date -u +%FT%TZ)."
  echo "set -eux"
  echo "ufw allow 80/tcp"
  echo "ufw allow 443/tcp"
  echo "# Then remove the per-range rules with: ufw status numbered; ufw delete <n>"
} > "$ROLLBACK"
chmod +x "$ROLLBACK"
ufw status numbered > /root/agoreum-ufw-before.txt
echo "rollback written to $ROLLBACK, previous rules saved to /root/agoreum-ufw-before.txt"

# Step 1: add before removing, so Cloudflare is never locked out mid-change.
while read -r cidr; do
  [ -n "$cidr" ] || continue
  ufw allow proto tcp from "$cidr" to any port 80,443 comment 'cloudflare'
done < "$TMP/v4"
while read -r cidr; do
  [ -n "$cidr" ] || continue
  ufw allow proto tcp from "$cidr" to any port 80,443 comment 'cloudflare'
done < "$TMP/v6"

# Step 2: drop the world-open rules. `ufw delete allow` is idempotent and exits
# non-zero when the rule is already gone, which is not an error here.
ufw delete allow 80/tcp || true
ufw delete allow 443/tcp || true

echo
ufw status verbose
echo
echo "Done. Verify from another machine that https://agoreum.xyz still serves,"
echo "and that a direct request to the origin address now times out."
echo "If anything is wrong: $ROLLBACK"
