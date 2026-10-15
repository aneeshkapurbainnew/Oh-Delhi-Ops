#!/bin/sh
# Update the server to the latest version on GitHub (run from ~/ohdelhi-ops/deploy):
#   ./update.sh            -> latest main
#   ./update.sh v1.2.0     -> a specific released version (also how you roll back)
set -eu
cd "$(dirname "$0")/.."
git fetch --tags --quiet origin
if [ "${1:-}" ]; then
  git checkout --quiet "$1"
else
  git checkout --quiet main && git pull --ff-only --quiet origin main
fi
echo "Deploying version $(cat VERSION) ($(git rev-parse --short HEAD))"
cd deploy
docker compose up -d --build
docker image prune -f >/dev/null
sleep 5
docker compose exec -T api python -c "import urllib.request,json;print('API says:',json.load(urllib.request.urlopen('http://localhost:8000/api/health')))"
