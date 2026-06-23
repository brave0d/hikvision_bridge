#!/usr/bin/env sh
# Run lint and tests inside the local test container: scripts/test.sh [pytest args]
set -e
cd "$(dirname "$0")/.."
docker build -q -f scripts/Dockerfile.test -t hikvision-bridge-test . >/dev/null
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W 2>/dev/null || pwd):/work" hikvision-bridge-test \
  sh -c "ruff check . && ruff format --check . && python -m pytest -p no:cacheprovider $*"
