# Deployment Document — Team 5 Financial Literacy Service

## 1. Architecture overview
The system uses a React + TypeScript frontend, FastAPI backend, PostgreSQL 16 with pgvector for persistent relational and future vector data, and Redis for short-lived caching. The frontend calls FastAPI over HTTP. The backend queries PostgreSQL for durable records and Redis for cache operations. Insert the team's supplied slide 11 architecture diagram here, ideally as `docs/architecture.png`.

## 2. Services and ports
| Service | Image / language | Local port | Internal or exposed |
|---|---|---:|---|
| Frontend | React/TypeScript, served by Nginx | 5173 → 80 | Exposed locally |
| Backend | Python 3.12, FastAPI/Uvicorn | 8000 | Exposed locally |
| PostgreSQL + pgvector | `pgvector/pgvector:pg16` | 5432 | Exposed for local development; internal in production |
| Redis | `redis:7-alpine` | 6379 | Exposed for local development; internal in production |

Ports are local-development defaults only. Instructor will coordinate k3s ports.

## 3. Data and storage
- PostgreSQL/pgvector stores ticker metadata, daily price bars, news/search results, derived events, non-sensitive profile preferences, search history, and future text chunks/embeddings. Data persists in Docker volume `postgres_data`.
- Redis stores short-term cache entries. Local data persists in `redis_data`, but PostgreSQL remains the source of truth.
- Do not store API credentials, account numbers, or holdings in Git or this starter database.

## 4. Configuration
| Variable | Purpose |
|---|---|
| `POSTGRES_DB` | PostgreSQL database name |
| `POSTGRES_USER` | PostgreSQL user |
| `POSTGRES_PASSWORD` | Local database password |
| `DATABASE_URL` | Backend PostgreSQL connection string |
| `REDIS_URL` | Backend Redis connection string |
| `CORS_ORIGINS` | Allowed browser origins |
| `ALPHA_VANTAGE_API_KEY` | Future market-data ingestion |
| `TAVILY_API_KEY` | Future news/search ingestion |
| `OPENAI_API_KEY` | Optional embedding provider |
| `ANTHROPIC_API_KEY` | Optional agent integration |

Use local `.env` or deployment secret management for actual values. Commit `.env.example` only.

## 5. Running locally on Docker
1. Install Docker Desktop/Engine with Compose.
2. Clone the repository and enter its directory.
3. Copy `.env.example` to `.env`.
4. Start: `docker compose up --build`
5. Check: `curl http://localhost:8000/health`, `curl http://localhost:8000/db/health`, and `curl http://localhost:8000/cache/health`.
6. Open frontend `http://localhost:5173`; API docs `http://localhost:8000/docs`.
7. Stop with `docker compose down`. `docker compose down -v` also permanently deletes local volumes.

## 6. Private k3s cloud deployment placeholder
**Reserved for instructor completion.** Instructor will configure k3s services, ports, secrets, ingress, and persistent volume claims after synchronizing service ports. Do not assume local ports are production ports.

## 7. Known issues and next steps
External Alpha Vantage/yfinance/Tavily ingestion is not wired in. Redis health and demo caching are available, but provider response caching is future work. pgvector is enabled and `document_chunks` is prepared, but embeddings and similarity search are not implemented. Sprint 3 should add ETL validation, provider normalization, deduplication, daily returns, rolling volatility, event/price joins, retries, and tests. Before deployment, keep database/cache ports private and use managed secrets.
