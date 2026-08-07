#!/usr/bin/env bash
#
# Regenerate infra/nginx/cloudflare_realip.conf from Cloudflare's published
# ranges.
#
# These ranges are what tells nginx which peers are allowed to speak for someone
# else. If Cloudflare adds a range and this file is stale, requests arriving
# through that new range keep the edge address as $remote_addr: rate limits start
# bucketing a whole edge together and session records show the edge rather than
# the visitor. If a range is removed and left here, an address that is no longer
# Cloudflare's would be trusted to set CF-Connecting-IP, which is the more
# serious direction. Run this when Cloudflare announces a change.
#
# Writes the file and prints a diff. It does not commit, and it does not reload
# nginx: review the diff, commit, and let the normal deploy apply it.
set -euo pipefail

cd "$(dirname "$0")/.."
OUT="infra/nginx/cloudflare_realip.conf"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fsS --max-time 30 https://www.cloudflare.com/ips-v4 -o "$TMP/v4"
curl -fsS --max-time 30 https://www.cloudflare.com/ips-v6 -o "$TMP/v6"

# A truncated or error response must never overwrite a working allowlist: an
# empty file would mean nginx trusts nobody to set the header, and every request
# would be attributed to the Cloudflare edge.
[ -s "$TMP/v4" ] || { echo "IPv4 list came back empty, refusing to write" >&2; exit 1; }
[ -s "$TMP/v6" ] || { echo "IPv6 list came back empty, refusing to write" >&2; exit 1; }

{
  sed -n '1,/^$/p' "$OUT" | sed '/^$/d'
  echo
  echo "# IPv4"
  sed 's/^/set_real_ip_from /; s/$/;/' "$TMP/v4"
  echo
  echo "# IPv6"
  sed 's/^/set_real_ip_from /; s/$/;/' "$TMP/v6"
  echo
  echo "real_ip_header CF-Connecting-IP;"
  echo "real_ip_recursive off;"
} > "$TMP/out"

mv "$TMP/out" "$OUT"
echo "Wrote $OUT ($(grep -c set_real_ip_from "$OUT") ranges)."
git --no-pager diff -- "$OUT" || true
