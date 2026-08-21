#!/usr/bin/env bash
# pixelbench runner.
#
# Two ways to reach the gateway:
#
#   Local  — the endpoint is reachable from here (a published port or localhost):
#              BENCH_BASE_URL=http://localhost:8000/v1 BENCH_MODEL=my-model ./run.sh
#
#   In a container — the gateway is only on a Compose network (e.g. the bundled
#   Pixelspace model at http://model:8000/v1). Point at the host and container;
#   the script ships bench.ts in and runs it there, reusing that container's env:
#              HOST=user@host CONTAINER=pixelspace-api-1 ./run.sh
#
# Any BENCH_* variable is forwarded to the benchmark either way. Results are
# saved to results-<timestamp>.md next to this script.
set -euo pipefail

HOST="${HOST:-}"
CONTAINER="${CONTAINER:-pixelspace-api-1}"
HERE="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date +%Y%m%dT%H%M%SZ)"
OUT="$HERE/results-$STAMP.md"

# Collect BENCH_* from this shell to forward.
ENV_ARGS=()
while IFS='=' read -r name _; do
  [[ "$name" == BENCH_* ]] && ENV_ARGS+=("$name=${!name}")
done < <(env)

if [[ -z "$HOST" ]]; then
  echo "→ running locally (results → $OUT)"
  env "${ENV_ARGS[@]}" bun "$HERE/bench.ts" | tee "$OUT"
else
  echo "→ shipping bench.ts to $HOST:$CONTAINER"
  ssh "$HOST" "cat > /tmp/pixelbench.ts && docker cp /tmp/pixelbench.ts $CONTAINER:/tmp/pixelbench.ts >/dev/null" < "$HERE/bench.ts"
  echo "→ running in container (results → $OUT)"
  DOCKER_ENV=()
  for kv in "${ENV_ARGS[@]}"; do DOCKER_ENV+=(-e "$kv"); done
  # shellcheck disable=SC2029
  ssh "$HOST" "docker exec ${DOCKER_ENV[*]} $CONTAINER bun /tmp/pixelbench.ts" | tee "$OUT"
fi

echo "✓ saved $OUT"
