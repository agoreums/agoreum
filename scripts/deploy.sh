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
$COMPOSE build api web indexer webhooks emails subscriptions-indexer

# A build can install the right dependencies and still ship the wrong ones.
#
# The web image ran `npm ci` from the lockfile and then copied apps/web over the
# top, which replaced the freshly installed tree with whatever node_modules was
# lying on this host. It had been there since July. Production served Next
# 16.2.11 for two weeks while the lockfile pinned 16.3.0, so a bump made
# specifically to clear three high advisories never arrived, and every deploy
# reported success throughout.
#
# The root fix is the .dockerignore, and the Dockerfile now copies in an order
# that survives its absence. This is the check that would actually have caught
# it, and it has to run here: a CI runner has no stale tree, so the fault is
# invisible there and only appears on a machine that has ever run npm locally.
log "verify the built image matches the lockfile"
EXPECTED=$(node -p "require('./apps/web/package-lock.json').packages['node_modules/next'].version" 2>/dev/null \
  || python3 -c "import json;print(json.load(open('apps/web/package-lock.json'))['packages']['node_modules/next']['version'])")
ACTUAL=$($COMPOSE run --rm --no-deps --entrypoint node web \
  -p "require('/srv/app/node_modules/next/package.json').version" 2>/dev/null | tr -d '\r\n')
if [ "${EXPECTED}" != "${ACTUAL}" ]; then
  echo "FATAL: web image ships next ${ACTUAL} but the lockfile pins ${EXPECTED}" >&2
  echo "the build context is contaminated; check .dockerignore and apps/web/node_modules" >&2
  exit 1
fi
echo "  next ${ACTUAL} matches the lockfile"

log "run migrations"
$COMPOSE run --rm api alembic upgrade head

log "recreate app + support services"
$COMPOSE up -d api web indexer webhooks emails subscriptions-indexer umami monitor

# Bind-mounted files do not redeploy themselves.
#
# A service that mounts a file from the repo onto a stock image has no image to
# rebuild, so `up -d` sees nothing changed and leaves the old process running
# with whatever it read at start. The file on disk is new and the behaviour is
# old, which is the worst shape a deploy can take: everything reports success.
#
# This is not hypothetical. An added governance alert sat undeployed for hours
# while the runbook claimed the event was watched, and a real settlement passed
# unannounced. nginx already had bespoke handling below for the same reason; the
# rule is general, so anything else mounting repo files belongs here too.
#
# The monitor is stateless and its script changes often, so it is recreated every
# time rather than conditionally.
log "recreate monitor so it picks up scripts/monitor.py"
$COMPOSE up -d --force-recreate monitor

# Umami mounts the database CA certificate. That file changes about once a year,
# so recreating analytics on every deploy would be churn for nothing; it is
# recreated only when the mounted file actually changed in this deploy.
if ! git diff --quiet "${BEFORE}" "${AFTER}" -- infra/certs; then
  log "database CA changed, recreating umami"
  $COMPOSE up -d --force-recreate umami
fi

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

# Apply container-level changes before reloading, because a reload cannot make
# one. Config files are bind mounted, so edits to a file that is *already*
# mounted take effect on reload, but adding a *new* mount needs the container
# recreated. Reloading first would therefore apply half a change: the edited
# files would go live while the new file stayed absent. That is worse than
# either state on its own. Concretely, pointing CF-Connecting-IP at $remote_addr
# without cloudflare_realip.conf present would resolve every visitor to the
# Cloudflare edge and collapse every rate limit bucket onto a handful of
# addresses. `up -d` recreates only when the service definition actually
# changed, so this is a no-op on an ordinary deploy.
log "apply any nginx mount or service changes"
$COMPOSE up -d nginx

# nginx resolves upstream container IPs once, at load time. Recreating api/web
# gives them new IPs, so nginx must re-read its config or it keeps proxying to the
# old, now-dead containers and every request 502s. A reload re-resolves without a
# restart (zero downtime); fall back to a recreate if the reload cannot run.
log "reload nginx so it re-resolves the new upstream IPs"
$COMPOSE exec -T nginx nginx -s reload 2>/dev/null || $COMPOSE up -d --force-recreate nginx

# The real test: does the public site actually serve? This traverses Cloudflare
# and nginx back to web, so it catches exactly the 502 a stale upstream causes, 
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

# Every deploy leaves BuildKit cache behind and nothing else ever removes it.
# Left alone it grew to 88GB, 76 percent of the disk, at roughly a gigabyte per
# deploy-day, and the first anyone would have heard of it was a full disk taking
# the database's WAL or a container's logs down with it. Bounded here, after the
# site is confirmed serving, so a slow prune can never extend an outage window.
# 20GB keeps recent layers so ordinary deploys stay incremental.
log "bound the build cache"
docker builder prune -f --keep-storage 20GB >/dev/null 2>&1 || true

echo "deploy ${AFTER} complete: api healthy and site serving"
