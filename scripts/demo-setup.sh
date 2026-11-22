#!/usr/bin/env bash
# One-command demo setup. Brings the Financial Literacy stack to a verified, demo-ready state on any
# machine with Docker, and repairs a stale one: builds images, applies every SQL migration, seeds prices,
# metadata and news, indexes the news, builds the Spark risk profiles if they are missing, pulls the local
# model if the compose profile is in use, loads the committed demo answers into the Redis cache, and
# checks the showcase question end to end. Safe to run repeatedly.
#
#   scripts/demo-setup.sh            repair / refresh in place (keeps data and the model)
#   scripts/demo-setup.sh --fresh    wipe the project's volumes first (asks unless --yes)
#   scripts/demo-setup.sh --spark    force the Spark jobs even if risk profiles exist
#   scripts/demo-setup.sh --no-model skip the Ollama pull
#
# Environment: DEMO_PROJECT (compose project name, default finlit), DEMO_API (default http://localhost:8000).
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT=${DEMO_PROJECT:-finlit}
API=${DEMO_API:-http://localhost:8000}
FRESH=0; MODEL=1; YES=0; SPARK=auto
for arg in "$@"; do
  case "$arg" in
    --fresh) FRESH=1 ;;
    --no-model) MODEL=0 ;;
    --yes|-y) YES=1 ;;
    --spark) SPARK=1 ;;
    --no-spark) SPARK=0 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

dc() { docker compose -p "$PROJECT" "$@"; }
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
envval() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//' | xargs || true; }

# ---------------------------------------------------------------- preflight
step "Preflight"
docker version >/dev/null 2>&1 || { echo "Docker is not reachable. Start Docker Desktop and retry." >&2; exit 1; }
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Add TAVILY_API_KEY for live news; the committed demo answers work without it."
fi
PG_USER=$(envval POSTGRES_USER); PG_USER=${PG_USER:-team5}
PG_DB=$(envval POSTGRES_DB);     PG_DB=${PG_DB:-financial_literacy}
TAVILY=$(envval TAVILY_API_KEY)
LLM_BASE_URL=$(envval LLM_BASE_URL)
LLM_MODEL=$(envval LLM_MODEL);   LLM_MODEL=${LLM_MODEL:-qwen2.5:7b-instruct}
PROFILE=()
case "$LLM_BASE_URL" in *ollama:*) PROFILE=(--profile local-llm) ;; esac
echo "project=$PROJECT api=$API model=$LLM_MODEL local-llm=$([ ${#PROFILE[@]} -gt 0 ] && echo yes || echo no) tavily=$([ -n "$TAVILY" ] && echo set || echo missing)"

# ---------------------------------------------------------------- fresh start
if [ "$FRESH" = 1 ]; then
  step "Fresh start: removing containers and volumes of project $PROJECT"
  if [ "$YES" != 1 ]; then
    read -r -p "This deletes the database, cached payloads, Spark output, the local model and the answer cache. Continue? [y/N] " reply
    case "$reply" in y|Y|yes|YES) ;; *) echo "aborted"; exit 1 ;; esac
  fi
  dc "${PROFILE[@]}" down -v --remove-orphans
fi

# ---------------------------------------------------------------- build + start
step "Building and starting services"
dc "${PROFILE[@]}" up --build -d --wait --remove-orphans

step "Waiting for the API (first boot downloads the embedding model)"
for i in $(seq 1 90); do
  if curl -fsS -m 5 "$API/health" >/dev/null 2>&1 && curl -fsS -m 5 "$API/db/health" >/dev/null 2>&1; then
    echo "API healthy after $((i * 5))s"; break
  fi
  if [ "$i" = 90 ]; then echo "API did not become healthy; see: docker compose -p $PROJECT logs backend" >&2; exit 1; fi
  sleep 5
done

# ---------------------------------------------------------------- schema
step "Applying SQL migrations (all are idempotent)"
for f in backend/sql/migrations/*.sql; do
  printf '  %s ... ' "$(basename "$f")"
  dc exec -T -e PGOPTIONS='-c client_min_messages=warning' db psql -q -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DB" < "$f" >/dev/null && echo ok
done

# ---------------------------------------------------------------- data
step "Seeding prices and company metadata (cache-first; only missing or stale data hits the provider)"
dc exec -T backend python -m app.ingestion seed-prices | tail -2
dc exec -T backend python -m app.ingestion seed-metadata | tail -1

step "News"
if [ -n "$TAVILY" ]; then
  for q in "Nvidia stock" "NVDA earnings" "Why did Nvidia stock fall this week" "Nvidia shares drop" "inflation bond prices"; do
    dc exec -T backend python -m app.ingestion news --query "$q" --days 14 | tail -1
  done
else
  echo "TAVILY_API_KEY not set: skipping news ingestion (stored articles, if any, are kept)"
fi
printf 'indexing news: '; curl -fsS -m 600 -X POST "$API/search/index-news"; echo

# ---------------------------------------------------------------- spark risk profiles
RISK_ROWS=$(dc exec -T db psql -tA -U "$PG_USER" -d "$PG_DB" -c "SELECT count(*) FROM risk_profiles" 2>/dev/null | tr -d '[:space:]' || echo 0)
if [ "$SPARK" = 1 ] || { [ "$SPARK" = auto ] && [ "${RISK_ROWS:-0}" = 0 ]; }; then
  step "Spark: Bronze/Silver, Gold features, KMeans risk profiles (several minutes)"
  for job in bronze_silver.py gold_features.py cluster_risk_profiles.py; do
    printf '  %s ... ' "$job"
    dc exec -T spark spark-submit "jobs/$job" 2>&1 | grep -vE 'WARN|INFO' | tail -1
  done
else
  step "Spark risk profiles present ($RISK_ROWS rows); skipping jobs (use --spark to rebuild)"
fi

# ---------------------------------------------------------------- local model
if [ ${#PROFILE[@]} -gt 0 ] && [ "$MODEL" = 1 ]; then
  step "Local model $LLM_MODEL"
  if dc exec -T ollama ollama list 2>/dev/null | grep -q "^${LLM_MODEL}"; then
    echo "already present"
  else
    dc exec -T ollama ollama pull "$LLM_MODEL"
  fi
fi

# ---------------------------------------------------------------- demo answers
step "Loading committed demo answers into the answer cache"
dc exec -T backend python -m app.orchestrator.cache load /app/app/demo/ask_answers.json --replace

# ---------------------------------------------------------------- verify
step "Verification"
dc exec -T backend python -m app.ingestion status | tail -4
RISK_ROWS=$(dc exec -T db psql -tA -U "$PG_USER" -d "$PG_DB" -c "SELECT count(*) FROM risk_profiles" | tr -d '[:space:]')
CHUNKS=$(dc exec -T db psql -tA -U "$PG_USER" -d "$PG_DB" -c "SELECT count(*) FROM document_chunks WHERE embedding IS NOT NULL" | tr -d '[:space:]')
echo "risk_profiles: $RISK_ROWS rows, indexed news chunks: $CHUNKS"
curl -fsS -m 60 -X POST "$API/ask" -H 'Content-Type: application/json' \
  -d '{"query":"What is the current stock price trend for NVDA?"}' \
  | python3 -c 'import json,sys
d = json.load(sys.stdin); g = d["governance"]
print("showcase question: status=%s cached=%s citations=%d generator=%s" % (g["status"], d["cached"], sum(c["cited"] for c in d["citations"]), d["generator"]))
sys.exit(0 if d["cached"] and g["status"] == "PASS" else 1)' || { echo "showcase question is not served from cache with PASS; check the demo answers file" >&2; exit 1; }
dc ps --format 'table {{.Service}}\t{{.Status}}'
printf '\nReady. Dashboard: http://localhost:5173   API docs: %s/docs\n' "$API"
