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

# A credential written in two places gets rotated in one.
#
# On 2026-08-21 the Alchemy key was rotated, ALCHEMY_API_KEY was updated and the
# two ALCHEMY_BASE_URL_* variables embedding the same key were not. Production
# kept serving, every health endpoint reported ok, and the indexer 401ed on
# every poll. Orders would have stopped being funded or settled with nothing
# saying so.
#
# Checked before migrations rather than after the app comes up, because the
# point is to refuse to deploy onto a configuration that is already wrong rather
# than to notice afterwards.
log "check the environment does not disagree with itself"
if ! python3 scripts/check_env_consistency.py .env; then
  echo "DEPLOY FAILED: a credential in .env is defined twice with different values"
  echo "  rotate every place it appears, not only the standalone variable"
  exit 1
fi

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

# A single-file bind mount points at an inode, not a path. `git pull` replaces
# these files rather than editing them in place, so the container keeps serving
# the copy it started with, and `up -d` sees an unchanged service definition and
# does nothing. `nginx -s reload` then re-reads the same stale file and succeeds,
# which is why the recreate fallback below never fired.
#
# The effect, measured on 2026-08-16: every nginx configuration change since the
# container was created on 2026-08-09 had silently not taken effect, including
# routing and rate limiting. Nothing failed. The deploy went green each time.
#
# So the running config is compared against disk rather than assumed to follow
# it, and the container is recreated only when they actually differ, which keeps
# an ordinary deploy free of an unnecessary blip.
log "check the running nginx config against the files on disk"
nginx_stale=false
for pair in "infra/nginx/agoreum.conf:/etc/nginx/conf.d/default.conf"             "infra/nginx/nginx.conf:/etc/nginx/nginx.conf"             "infra/nginx/proxy_headers.conf:/etc/nginx/conf.d/proxy_headers.conf"             "infra/nginx/cloudflare_realip.conf:/etc/nginx/conf.d/cloudflare_realip.conf"; do
    host_file="${pair%%:*}"
    container_file="${pair##*:}"
    on_disk=$(md5sum "$host_file" | cut -d' ' -f1)
    in_container=$($COMPOSE exec -T nginx md5sum "$container_file" 2>/dev/null | cut -d' ' -f1)
    if [ "$on_disk" != "$in_container" ]; then
        log "  stale: $host_file"
        nginx_stale=true
    fi
done

if [ "$nginx_stale" = true ]; then
    log "recreating nginx so it picks up the changed configuration"
    $COMPOSE up -d --force-recreate nginx
    sleep 3
fi

# nginx resolves upstream container IPs once, at load time. Recreating api/web
# gives them new IPs, so nginx must re-read its config or it keeps proxying to the
# old, now-dead containers and every request 502s. A reload re-resolves without a
# restart (zero downtime); fall back to a recreate if the reload cannot run.
log "reload nginx so it re-resolves the new upstream IPs"
$COMPOSE exec -T nginx nginx -s reload 2>/dev/null || $COMPOSE up -d --force-recreate nginx

# The real test: does the public site actually serve? This traverses Cloudflare
# and nginx back to web, so it catches exactly the 502 a stale upstream causes, 
# which an api-only health check would miss.
# Assert rather than trust. If the running config still does not match disk
# after a recreate, the deploy has not applied what it was asked to apply, and
# saying so loudly is better than a green deploy serving yesterday's routing.
log "confirm the running nginx config is the one in this commit"
for pair in "infra/nginx/agoreum.conf:/etc/nginx/conf.d/default.conf"             "infra/nginx/nginx.conf:/etc/nginx/nginx.conf"             "infra/nginx/proxy_headers.conf:/etc/nginx/conf.d/proxy_headers.conf"             "infra/nginx/cloudflare_realip.conf:/etc/nginx/conf.d/cloudflare_realip.conf"; do
    host_file="${pair%%:*}"
    container_file="${pair##*:}"
    on_disk=$(md5sum "$host_file" | cut -d' ' -f1)
    in_container=$($COMPOSE exec -T nginx md5sum "$container_file" 2>/dev/null | cut -d' ' -f1)
    if [ "$on_disk" != "$in_container" ]; then
        log "FAILED: nginx is still serving a different $container_file than this commit"
        exit 1
    fi
done
log "  nginx configuration matches"

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

# A settlement receipt is only worth anything to somebody who trusts nothing we
# say, and that person needs two things at once: the key document reachable from
# the open internet, and a key actually in it. Both have already failed here.
#
# The routing half failed for a week and is what the location blocks above fix.
# The signing half is the more dangerous of the two, because nothing about it
# fails. An unsigned receipt is a deliberate, documented mode: the API still
# issues one, it still carries every coordinate needed to check the chain, and
# the only difference is "signature": null. So a droplet that loses
# RECEIPT_SIGNING_KEY keeps serving 200s, keeps passing every health check, and
# quietly stops attesting to anything. That is precisely the shape this project
# keeps finding, where absence is indistinguishable from success.
#
# A third way to fail was found the day after this check was written, and it is
# why the assertion moved out of here into its own script. The first version
# used curl, which the edge was happy to serve. A verifier written with a
# standard library was getting 403 from Cloudflare's browser integrity check the
# whole time, so the guard was passing while the property it existed to protect
# was broken for the client most likely to exercise it.
#
# The lesson is the one this project keeps relearning: a check passes for the
# client it happens to use. check_public_verifiability.py therefore asserts with
# the exact user agent that was refused, and asserts the exemption did not
# spread past /.well-known/, since an exemption covering the whole zone would
# look identical from these documents alone.
log "confirm a stranger's software can still verify a receipt"
if ! python3 scripts/check_public_verifiability.py; then
  echo "DEPLOY FAILED: the receipts key document is not publicly verifiable"
  echo "  either nginx is not routing that path to the api, RECEIPT_SIGNING_KEY"
  echo "  is missing so receipts are issued unsigned, or the edge is refusing"
  echo "  the plain client a third-party verifier would use"
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
