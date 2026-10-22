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
| Backend | Python 3.12, FastAPI | 8000 |
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

- Price bars: Alpha Vantage (full history, one call per ticker), yfinance fallback. 25 calls/day counted in a rolling 24h window, every attempt counts including rate-limit and premium notices.
- Ticker metadata: yfinance, free.
- News / search: Tavily. Dedup on normalized URL then title+date, in `dedup.py`.

Keys go in `.env`: `ALPHA_VANTAGE_API_KEY`, `TAVILY_API_KEY`.

```bash
docker compose exec backend python -m app.ingestion budget                 # calls used / remaining
docker compose exec backend python -m app.ingestion seed-prices --dry-run  # plan only
docker compose exec backend python -m app.ingestion seed-prices            # default list in tickers.py, or --tickers NVDA,AMD
docker compose exec backend python -m app.ingestion seed-metadata
docker compose exec backend python -m app.ingestion news --query "Nvidia earnings" --days 7
docker compose exec backend python -m app.ingestion replay                 # rebuild tables from raw_payloads, no api calls
docker compose exec backend python -m app.ingestion status
```
`--refresh` forces a new API call for cached data. Same operations over HTTP: `POST /ingest/prices/{symbol}`, `POST /ingest/metadata/{symbol}`, `POST /ingest/news`, `GET /ingest/budget`, `GET /ingest/status`; read back with `GET /price-bars`, `GET /ticker-metadata/{symbol}`, `GET /search-results`.

Tests:
```bash
cd backend && pip install -r requirements-dev.txt
pytest                                                   # offline
TEST_DATABASE_URL=postgresql://team5:local_dev_only@localhost:5433/financial_literacy pytest -m integration
```

## GitHub collaboration
Push this starter to your team's own repository. Grant the instructor account `qcheng1-prog` the access level required by your course. Every teammate should make their own genuine commit, preferably through a branch and pull request. Do not fabricate commits. Never commit `.env` or API keys; commit `.env.example` only.

## Current limitations / next steps
Embeddings, vector search and Redis response caching are not implemented. Ingestion covers price bars, ticker metadata and news/search results; events with window returns, daily returns, rolling volatility and fuzzy dedup are Sprint 3.
