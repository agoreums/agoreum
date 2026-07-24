#!/usr/bin/env bash
#
# Production deploy, run on the droplet by the CD job after CI passes on main.
#
# Pulls the merged commit, rebuilds the images whose layers changed, runs
# migrations, recreates the services, and then *verifies* the API comes back
# healthy. If it does not, the script exits non-zero so the CD job fails loudly
# rather than leaving a half-deployed stack looking green.
set -euo pipefail

REPO=/root/agoreum
COMPOSE="docker compose -f ${REPO}/docker-compose.prod.yml"
cd "$REPO"

log() { printf '\n=== %s ===\n' "$1"; }

log "pull main"
BEFORE=$(git rev-parse --short HEAD)
git fetch origin main
git reset --hard origin/main
AFTER=$(git rev-parse --short HEAD)
echo "deploying ${BEFORE} -> ${AFTER}"

log "build images"
$COMPOSE build api web indexer

log "run migrations"
$COMPOSE run --rm api alembic upgrade head

log "recreate app + support services"
$COMPOSE up -d api web indexer umami

log "verify api health"
ok=false
for i in $(seq 1 24); do
  status=$($COMPOSE exec -T api curl -fsS http://127.0.0.1:8000/api/v1/health/ready 2>/dev/null \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('status',''))" 2>/dev/null || true)
  if [ "$status" = "ok" ]; then ok=true; break; fi
  sleep 5
done
if [ "$ok" != true ]; then
  echo "DEPLOY FAILED: api did not report healthy after recreate"
  $COMPOSE ps
  exit 1
fi

# nginx resolves upstream container IPs once, at load time. Recreating api/web
# gives them new IPs, so nginx must re-read its config or it keeps proxying to the
# old, now-dead containers and every request 502s. A reload re-resolves without a
# restart (zero downtime); fall back to a recreate if the reload cannot run.
log "reload nginx so it re-resolves the new upstream IPs"
$COMPOSE exec -T nginx nginx -s reload 2>/dev/null || $COMPOSE up -d --force-recreate nginx

# The real test: does the public site actually serve? This traverses Cloudflare
# and nginx back to web, so it catches exactly the 502 a stale upstream causes —
# which an api-only health check would miss.
log "verify the public site serves end to end"
served=false
for i in $(seq 1 18); do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 https://agoreum.xyz/en || true)
  echo "  agoreum.xyz/en -> ${code}"
  if [ "$code" = "200" ]; then served=true; break; fi
  sleep 5
done
if [ "$served" != true ]; then
  echo "DEPLOY FAILED: the public site is not serving after deploy"
  $COMPOSE ps
  exit 1
fi

echo "deploy ${AFTER} complete: api healthy and site serving"
