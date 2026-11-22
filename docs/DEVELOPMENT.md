# Development guide

Operational detail for working on the Financial Literacy Service. The [README](../README.md) is the short, demo-facing overview.

## Running the stack

```bash
cp .env.example .env            # add TAVILY_API_KEY; model settings are optional
scripts/demo-setup.sh           # build, migrate, seed, Spark profiles, demo answers, verify (safe to repeat)
scripts/demo-setup.sh --fresh   # wipe this project's volumes first
docker compose up --build       # plain start without seeding
```

Health checks: `curl localhost:8000/health`, `/db/health`, `/cache/health`. API docs at http://localhost:8000/docs. Stop with `docker compose down`; `down -v` also deletes the volumes (database, cached payloads, model, answer cache).

| Service | Technology | Local port |
|---|---|---:|
| Frontend | React + TypeScript, served by Nginx (proxies `/api` to the backend) | 5173 |
| Backend | Python 3.12, FastAPI | 8000 (container 8605) |
| PostgreSQL + pgvector | pgvector/pgvector:pg16 | 5433 (container 5432) |
| Redis | Redis 7 | internal |
| Spark | Spark 3.5 single node, idle until a job is submitted | internal |
| Ollama (optional) | `--profile local-llm`, model volume `ollama_models` | internal |

The initialization SQL runs only when the database volume is first created; `backend/sql/migrations/` holds idempotent scripts for older volumes, and the setup script applies all of them every run.

## Database

- `raw_payloads`: every external API response as JSONB; normalization reads from here so API budget is spent once.
- `ticker_metadata`, `price_bars` (unique by symbol and date; split- and dividend-adjusted close), `search_results` (deduplicated by normalized URL, then title and date).
- `document_chunks`: article chunks with 384-d MiniLM embeddings.
- `financial_concepts`, `concept_relationships`: the ontology used for query expansion.
- `gold_symbol_metrics`, `risk_profiles`: Spark output (per-symbol summary; one row per symbol per quarter).
- `events`, `user_profiles`, `search_history`: dated events (window returns not built), non-sensitive preferences, query log.

## Ingestion

`backend/app/ingestion/`: one module per provider (fetch / classify / normalize), `pipeline.py` ties them together.

```
api -> raw_payloads -> normalize -> price_bars / ticker_metadata / search_results
```

```bash
docker compose exec backend python -m app.ingestion seed-prices            # default list in tickers.py, or --tickers NVDA,AMD
docker compose exec backend python -m app.ingestion seed-metadata
docker compose exec backend python -m app.ingestion news --query "Nvidia earnings" --days 7
docker compose exec backend python -m app.ingestion replay                 # rebuild tables from raw_payloads, no api calls
docker compose exec backend python -m app.ingestion status
curl -X POST localhost:8000/search/index-news                              # chunk + embed new articles
```

`--refresh` forces a new API call for cached data. Prices come from yfinance (full history, today's unfinished session skipped) and are refreshed when more than 24 hours old; if the refresh fails the cached history is served. Alpha Vantage is optional behind a 25-calls/day guard (`budget`, `seed-prices --dry-run`) but unused because the free tier gates the adjusted endpoint. The same operations exist over HTTP: `POST /ingest/prices/{symbol}`, `POST /ingest/metadata/{symbol}`, `POST /ingest/news`, `GET /ingest/status`; read back with `GET /price-bars`, `GET /ticker-metadata/{symbol}`, `GET /search-results`.

## Spark

See [spark/README.md](../spark/README.md) for the full pipeline and results.

```bash
docker compose exec spark spark-submit jobs/bronze_silver.py
docker compose exec spark spark-submit jobs/gold_features.py
docker compose exec spark spark-submit jobs/cluster_risk_profiles.py
```

The clustering job writes `risk_profiles`, served by `GET /risk-profiles/{symbol}`, shown as the dashboard's "Historical risk profile" card, and offered to `/ask` as a numbered source for ticker questions.

## The `/ask` orchestrator

```
POST /ask {"query": "What is an ETF?", "top_k": 5, "debug": false, "cache": true}
-> {"answer": "... [1]", "citations": [...], "governance": {"intent", "mode", "status", "reasons"},
    "concepts": [...], "glossary": [...], "generated": true, "generator": "...", "cached": false, "trace": [...]}
```

`governance.status`: `PASS`; `REVIEW` (a claim lacks a citation, a source is unregistered or user-generated, the answer rests on journalism alone, or a guardrail flagged advice-like wording that a rewrite did not clear); `BLOCK` (advice-like output rejected twice, glossary-only fallback returned); `SKIPPED` (transactional or out-of-scope requests get a scripted reply). `debug: true` adds a per-step trace with timings.

Retrieval details: glossary rows lead; hybrid search asks for three times `top_k` candidates and keeps registered publishers first (policy 6.1); rows under `RELEVANCE_FLOOR` (0.40) are dropped; cited-information mode fetches news on a miss when results are thin (`MIN_SIMILARITY` 0.45). Evidence excerpts are capped at 600 characters each to keep CPU prompt processing short.

### Model settings

| Variable | Meaning |
|---|---|
| `HF_TOKEN` | Hugging Face token for the Inference API (the account also needs inference credits; free accounts get HTTP 402). |
| `LLM_MODEL` | Default `Qwen/Qwen2.5-72B-Instruct` on Hugging Face; `qwen2.5:7b-instruct` for the local service. |
| `LLM_BASE_URL` | Any OpenAI-compatible `/v1` endpoint. `http://ollama:11434/v1` is the compose service; `http://host.docker.internal:11434/v1` reaches an Ollama on the host. |
| `LLM_PROVIDER` | `huggingface`, `openai_compatible`, or `stub` (deterministic, answers from the evidence itself; what the tests use). Inferred when unset. |
| `LLM_TIMEOUT_SECONDS` | Default 60; CPU-only local models need 300. |
| `LLM_TEMPERATURE` | Default 0.2; 0 makes repeated questions deterministic. |
| `PUBLIC_API_URL` | Base URL shown in the risk-profile citation. |

Local model without a token:

```bash
docker compose --profile local-llm up -d
docker compose exec ollama ollama pull qwen2.5:7b-instruct      # once, ~4.7 GB
# .env: LLM_PROVIDER=openai_compatible  LLM_BASE_URL=http://ollama:11434/v1  LLM_MODEL=qwen2.5:7b-instruct  LLM_TIMEOUT_SECONDS=300
```

On an 8-core CPU the 7B model processes prompts at roughly 10 tokens/s, so a fresh answer takes two to three minutes. The 3B model is about 2.5x faster but produced lower-quality citations in testing.

### Answer cache and demo answers

Generated answers are kept in Redis for `ASK_CACHE_TTL_SECONDS` (default one day) keyed by the normalized question, model and `top_k`. A repeat returns `cached: true` with `cached_at`; `"cache": false` forces a fresh call and refreshes the entry. Fallback, scripted and blocked answers are never cached.

`backend/app/demo/ask_answers.json` holds the showcase answers and is loaded at startup (`ASK_CACHE_SEED`; set it empty to disable). Loaded entries never expire. To regenerate and re-export them:

```bash
docker compose exec backend python -m app.orchestrator.cache dump /tmp/answers.json "What is an ETF?" "What is the current stock price trend for NVDA?"
docker compose cp backend:/tmp/answers.json backend/app/demo/ask_answers.json
docker compose exec backend python -m app.orchestrator.cache load /app/app/demo/ask_answers.json --replace   # or restart the backend
```

## Tests

```bash
cd backend && pip install -r requirements-dev.txt
pytest                                                   # offline, fixtures only
TEST_DATABASE_URL=postgresql://team5:local_dev_only@localhost:5433/financial_literacy pytest -m integration
```

Or inside the image without a local environment:

```bash
docker run --rm -v "$PWD/backend:/app:ro" -w /app <backend-image> sh -c "pip install -q pytest && pytest -q"
```

## Streamlit dashboard

`app.py` is a second front end against the same API (chat, prices and risk profile, stored news).

```bash
pip install -r requirements-dashboard.txt
streamlit run app.py          # backend at http://localhost:8000, override with BACKEND_API_URL
```

## Collaboration

Work on branches and open pull requests into `main`. Never commit `.env` or API keys; commit `.env.example` only. The instructor account `qcheng1-prog` has access to the repository.
