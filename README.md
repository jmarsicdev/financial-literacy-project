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
| PostgreSQL + pgvector | pgvector/pgvector:pg16 | 5432 |
| Redis | Redis 7 | 6379 |

## Database design
- `ticker_metadata`: company metadata.
- `price_bars`: daily OHLC price data, unique by symbol/date to support idempotent upserts.
- `search_results`: normalized Tavily/news results, deduplicated by normalized URL.
- `events`: dated news events and optional market-window metrics.
- `user_profiles`, `search_history`: non-sensitive preferences and search records.
- `document_chunks`: future terminology RAG chunks and optional vector embeddings.

PostgreSQL persists in the `postgres_data` Docker volume. Redis is a cache and persists locally in `redis_data`. The initialization SQL runs only when the database volume is first created; use migrations for future schema changes.

## GitHub collaboration
Push this starter to your team's own repository. Grant the instructor account `qcheng1-prog` the access level required by your course. Every teammate should make their own genuine commit, preferably through a branch and pull request. Do not fabricate commits. Never commit `.env` or API keys; commit `.env.example` only.

## Current limitations / next steps
External provider ingestion, real cache integration, embedding generation, and vector similarity search are not implemented yet. Sprint 3 should add ETL validation, provider normalization, URL/title/date deduplication, daily returns, rolling volatility, event/price joins, retry handling, and tests.
