# Team 5 — Financial Literacy Service

## Team members
- Josh Marsico
- Himaja Goda
- Jayden Parsons
- Michael Simms

## Project description
The Financial Literacy Service is an educational research assistant for beginner investors. It combines market data, financial news, and beginner-friendly terminology explanations with citations and guardrails against directive investment advice. This repository provides a starter React frontend, FastAPI backend, PostgreSQL with pgvector, and Redis cache.

## Run locally
Prerequisites: Docker Desktop/Engine with Docker Compose and Git.

```bash
git clone <team-repository-url>
cd <repository-directory>
cp .env.example .env
docker compose up --build
```

For a demo-ready stack in one command (builds, migrates, seeds prices/metadata/news, builds the Spark risk profiles, pulls the local model if configured, loads the committed demo answers, and verifies the showcase question), run:

```bash
scripts/demo-setup.sh            # repair or refresh in place; safe to repeat
scripts/demo-setup.sh --fresh    # wipe this project's volumes first
```

Open http://localhost:5173, API docs at http://localhost:8000/docs. Verify:
```bash
curl http://localhost:8000/health
curl http://localhost:8000/db/health
curl http://localhost:8000/cache/health
```
Stop with `docker compose down`. `docker compose down -v` also deletes persisted local data.

## Services
| Service | Technology | Local port |
|---|---|---:|
| Frontend | React + TypeScript, Nginx | 5173 |
| Backend | Python 3.12, FastAPI | 8000 (container 8605) |
| PostgreSQL + pgvector | pgvector/pgvector:pg16 | 5433 (container 5432) |
| Redis | Redis 7 | 6379 |

## Database design
- `ticker_metadata`: company metadata.
- `price_bars`: daily OHLC price data, unique by symbol/date to support idempotent upserts.
- `search_results`: normalized Tavily/news results, deduplicated by normalized URL.
- `events`: dated news events and optional market-window metrics.
- `user_profiles`, `search_history`: non-sensitive preferences and search records.
- `document_chunks`: future terminology RAG chunks and optional vector embeddings.
- `raw_payloads`: every external API response as JSONB. Normalization reads from here so API budget is only spent once.

PostgreSQL persists in the `postgres_data` Docker volume. Redis is a cache and persists locally in `redis_data`. The initialization SQL runs only when the database volume is first created; `backend/sql/migrations/` has scripts for older volumes.

## Ingestion
`backend/app/ingestion/`. One module per provider (fetch / classify / normalize), `pipeline.py` ties them together.

```
api -> raw_payloads -> normalize -> price_bars / ticker_metadata / search_results
```

- Price bars: yfinance (full history, split/dividend adjusted close, today's unfinished session is skipped). Alpha Vantage is optional: set a key and it's tried first with a 25 calls/day guard, but the free tier can't reach the adjusted endpoint so we don't use it.
- Ticker metadata: yfinance.
- News / search: Tavily. Dedup on normalized URL then title+date, in `dedup.py`.

Keys go in `.env`: `TAVILY_API_KEY` (and `ALPHA_VANTAGE_API_KEY` if you want it).

```bash
docker compose exec backend python -m app.ingestion seed-prices            # default list in tickers.py, or --tickers NVDA,AMD
docker compose exec backend python -m app.ingestion seed-metadata
docker compose exec backend python -m app.ingestion news --query "Nvidia earnings" --days 7
docker compose exec backend python -m app.ingestion replay                 # rebuild tables from raw_payloads, no api calls
docker compose exec backend python -m app.ingestion status
```
`--refresh` forces a new API call for cached data. `budget` and `seed-prices --dry-run` only matter if an Alpha Vantage key is set. Same operations over HTTP: `POST /ingest/prices/{symbol}`, `POST /ingest/metadata/{symbol}`, `POST /ingest/news`, `GET /ingest/budget`, `GET /ingest/status`; read back with `GET /price-bars`, `GET /ticker-metadata/{symbol}`, `GET /search-results`.

Tests:
```bash
cd backend && pip install -r requirements-dev.txt
pytest                                                   # offline
TEST_DATABASE_URL=postgresql://team5:local_dev_only@localhost:5433/financial_literacy pytest -m integration
```

## Orchestrator (`POST /ask`)
`backend/app/orchestrator/` ties the pieces together: governance classifies the question, hybrid search (plus the SEC glossary and, for ticker questions, stored price bars) supplies numbered evidence, the model writes a cited answer, and governance checks the answer before it is returned.

```
POST /ask {"query": "What is an ETF?", "top_k": 5, "debug": false}
-> {"answer": "... [1]", "citations": [...], "governance": {"intent", "mode", "status", "reasons"}, "concepts": [...], "glossary": [...]}
```

Answers the model produced are kept in Redis for `ASK_CACHE_TTL_SECONDS` (default one day) keyed by the normalized question and model; a repeat question returns the stored answer with `cached: true` and `cached_at`. Send `"cache": false` to force a fresh model call. Fallback, scripted and blocked answers are never cached.

Demo answers are committed in `backend/app/demo/ask_answers.json` and loaded into Redis when the backend starts (`ASK_CACHE_SEED`, default on; they never expire). A fresh clone therefore answers the showcase questions instantly without a model. To refresh them after regenerating:

```bash
docker compose exec backend python -m app.orchestrator.cache dump /tmp/answers.json "What is an ETF?" "What is the current stock price trend for NVDA?"
docker compose cp backend:/tmp/answers.json backend/app/demo/ask_answers.json
docker compose exec backend python -m app.orchestrator.cache load /app/app/demo/ask_answers.json --replace   # or just restart
```

`governance.status` is `PASS`, `REVIEW` (answer returned with caveats: a claim lacks a citation, a source is unregistered or user-generated, or the answer rests on journalism alone with no official data or regulator source behind it), `BLOCK` (advice-like output was rejected twice and a glossary-only answer is returned), or `SKIPPED` (transactional or out-of-scope requests get a scripted reply and no model call).

Model settings in `.env`:

| Variable | Meaning |
|---|---|
| `HF_TOKEN` | Hugging Face token. Required for the Inference API; the account also needs inference credits (free accounts get HTTP 402 otherwise). |
| `LLM_MODEL` | Model id. Default `Qwen/Qwen2.5-72B-Instruct` on Hugging Face; for Ollama use e.g. `qwen2.5:7b-instruct`. |
| `LLM_BASE_URL` | Any OpenAI-compatible `/v1` endpoint. Default is the Hugging Face router; `http://localhost:11434/v1` runs against a local Ollama. |
| `LLM_PROVIDER` | `huggingface`, `openai_compatible`, or `stub` (deterministic, no model). Inferred from the two settings above when unset. |
| `LLM_TIMEOUT_SECONDS` | Model call timeout, default 60. CPU-only local models need 180 or more. |

With no token and no base url the stub generator answers from the evidence itself, which is what the tests use.

Local model without a token: the compose file has an optional `ollama` service.

```bash
docker compose --profile local-llm up -d
docker compose exec ollama ollama pull qwen2.5:7b-instruct     # once, ~4.7 GB, kept in the ollama_models volume
# .env: LLM_PROVIDER=openai_compatible  LLM_BASE_URL=http://ollama:11434/v1  LLM_MODEL=qwen2.5:7b-instruct  LLM_TIMEOUT_SECONDS=300
```

Source tiers decide whether a cited answer passes: regulators (Tier 1), exchanges, market-data providers and this service's own stored prices and Spark risk profile (Tier 2) can carry a claim on their own; established journalism (Tier 3) passes only when the answer also cites a Tier 1 or Tier 2 source other than a glossary definition; user-generated or unregistered sources always send the answer to `REVIEW`.

## Spark layer and historical risk profiles
`spark/` holds the Sprint 4 pipeline (see `spark/README.md` for commands, record counts, and results): Bronze and Silver Parquet, Gold features, Spark SQL summaries, a KMeans clustering of each stock's behavior per quarter, and two next-day classifiers kept as a negative result.

The clustering job writes one row per symbol per quarter to the `risk_profiles` table, which is used in three places:

- `GET /risk-profiles` and `GET /risk-profiles/{symbol}`: latest quarter, share of quarters in each group, recent history.
- The React dashboard shows a "Historical risk profile" card after a ticker is loaded.
- `POST /ask` adds the profile as a numbered source when a question names a ticker, so the assistant cites computed figures instead of characterizing risk on its own.

A profile describes a past quarter. It is not a forecast and is always shown with its quarter.

```bash
docker compose exec backend python -m app.ingestion seed-prices
docker compose exec backend python -m app.ingestion seed-metadata
docker compose exec spark spark-submit jobs/bronze_silver.py
docker compose exec spark spark-submit jobs/gold_features.py
docker compose exec spark spark-submit jobs/cluster_risk_profiles.py
```

Cached price history is refreshed from yfinance once it is more than 24 hours old; if the refresh fails the older cached history is served.

## Streamlit dashboard
`app.py` is a second front end that talks to the same API: the chat tab calls `POST /ask`, the prices tab shows stored bars and the risk profile, and the news tab lists stored articles.

```bash
pip install -r requirements-dashboard.txt
streamlit run app.py          # backend expected at http://localhost:8000, override with BACKEND_API_URL
```

## GitHub collaboration
Push this starter to your team's own repository. Grant the instructor account `qcheng1-prog` the access level required by your course. Every teammate should make their own genuine commit, preferably through a branch and pull request. Do not fabricate commits. Never commit `.env` or API keys; commit `.env.example` only.

## Current limitations / next steps
Retrieval is implemented end to end: articles are chunked and embedded locally with MiniLM-L6 (384-d) into pgvector, hybrid search expands the query through the financial ontology, and `POST /ask` returns a cited, governance-checked answer. Still open: events with window returns are not built; Spark runs single-node; the model is hosted (Hugging Face) or local (Ollama) with no evaluation set yet; there is no authentication.
