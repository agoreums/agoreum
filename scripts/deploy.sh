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

log "recreate services"
$COMPOSE up -d api web indexer nginx umami

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

log "verify site serves"
code=$($COMPOSE exec -T nginx wget -q -O /dev/null -S http://127.0.0.1/healthz 2>&1 | awk '/HTTP\//{print $2; exit}')
echo "nginx /healthz -> ${code:-unknown}"

echo "deploy ${AFTER} complete and healthy"
