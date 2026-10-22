import os
import redis
from datetime import date
from typing import Literal
from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from psycopg.rows import dict_row
from .db import get_connection
from .ingestion import Ingestor
from .ingestion.config import load_settings
from .ingestion.store import PostgresStore

app = FastAPI(title="Team 5 Financial Literacy API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=False, allow_methods=["*"], allow_headers=["*"]
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

def cache():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)

def build_ingestor() -> Ingestor:
    return Ingestor(PostgresStore(), load_settings())

class PriceBarIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=15)
    date: date
    open: float = Field(ge=0)
    high: float = Field(ge=0)
    low: float = Field(ge=0)
    close: float = Field(ge=0)
    adjusted_close: float = Field(ge=0)
    volume: int = Field(ge=0)
    provider: str = Field(default="unknown", max_length=40)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value):
        return value.strip().upper()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/db/health")
def db_health():
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "query_result": row[0]}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

@app.get("/cache/health")
def cache_health():
    try:
        return {"status": "ok", "redis": cache().ping()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc

@app.get("/price-bars")
def list_price_bars(symbol: str = Query(min_length=1, max_length=15), limit: int = Query(100, ge=1, le=500)):
    try:
        with get_connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                "SELECT symbol, bar_date, open, high, low, close, adjusted_close, volume, provider, updated_at FROM price_bars WHERE symbol=%s ORDER BY bar_date DESC LIMIT %s",
                (symbol.strip().upper(), limit)
            ).fetchall()
        return {"items": rows, "count": len(rows)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not query price bars") from exc

@app.post("/price-bars")
def upsert_price_bar(bar: PriceBarIn):
    if bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(bar.open, bar.close, bar.high):
        raise HTTPException(status_code=422, detail="OHLC values are inconsistent")
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO price_bars (symbol,bar_date,open,high,low,close,adjusted_close,volume,provider) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (symbol,bar_date) DO UPDATE SET open=EXCLUDED.open,high=EXCLUDED.high,low=EXCLUDED.low,close=EXCLUDED.close,adjusted_close=EXCLUDED.adjusted_close,volume=EXCLUDED.volume,provider=EXCLUDED.provider,updated_at=now()",
                (bar.symbol, bar.date, bar.open, bar.high, bar.low, bar.close, bar.adjusted_close, bar.volume, bar.provider)
            )
        try:
            cache().delete(f"price-bars:{bar.symbol}")
        except Exception:
            pass
        return {"status": "saved", "symbol": bar.symbol, "date": bar.date}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not save price bar") from exc

@app.post("/cache/demo")
def cache_demo(key: str = "team5-demo", value: str = "hello", ttl_seconds: int = 60):
    if not 1 <= ttl_seconds <= 86400:
        raise HTTPException(status_code=422, detail="TTL must be between 1 and 86400 seconds")
    try:
        cache().set(key, value, ex=ttl_seconds)
        return {"status": "cached", "key": key, "ttl_seconds": ttl_seconds}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not write to Redis") from exc


@app.get("/ticker-metadata/{symbol}")
def get_ticker_metadata(symbol: str = Path(min_length=1, max_length=15)):
    try:
        with get_connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT symbol, company_name, sector, industry, exchange, market_cap, business_summary, provider, updated_at FROM ticker_metadata WHERE symbol=%s",
                (symbol.strip().upper(),)
            ).fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not query ticker metadata") from exc
    if row is None:
        raise HTTPException(status_code=404, detail="No metadata for that symbol")
    return row

@app.get("/search-results")
def list_search_results(
    query: str | None = Query(default=None, max_length=200, description="filter on the query that produced the result"),
    dated_only: bool = False,
    limit: int = Query(50, ge=1, le=500),
):
    sql = (
        "SELECT id, title, url, normalized_url, source_domain, score, published_at, query_text, provider, fetched_at, "
        "left(content, 300) AS content_preview FROM search_results"
    )
    clauses, args = [], []
    if query:
        clauses.append("query_text ILIKE %s")
        args.append(f"%{query.strip()}%")
    if dated_only:
        clauses.append("published_at IS NOT NULL")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY published_at DESC NULLS LAST, fetched_at DESC LIMIT %s"
    args.append(limit)
    try:
        with get_connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(sql, args).fetchall()
        return {"items": rows, "count": len(rows)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not query search results") from exc


def _result_response(result):
    body = result.to_dict()
    if result.status == "failed":
        raise HTTPException(status_code=502, detail=body)
    return body

@app.get("/ingest/budget")
def ingest_budget():
    try:
        return build_ingestor().av_budget().to_dict()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not read budget") from exc

@app.get("/ingest/status")
def ingest_status():
    try:
        return build_ingestor().store.table_counts()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not read ingestion status") from exc

@app.post("/ingest/prices/{symbol}")
def ingest_prices(
    symbol: str = Path(min_length=1, max_length=15),
    refresh: bool = Query(False, description="ignore cached payloads and call the provider"),
    fallback: bool = Query(True, description="fall back to yfinance when Alpha Vantage is unavailable"),
):
    try:
        result = build_ingestor().ingest_prices(symbol, refresh=refresh, allow_fallback=fallback)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Ingestion failed") from exc
    return _result_response(result)

@app.post("/ingest/metadata/{symbol}")
def ingest_metadata(symbol: str = Path(min_length=1, max_length=15), refresh: bool = False):
    try:
        result = build_ingestor().ingest_metadata(symbol, refresh=refresh)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Ingestion failed") from exc
    return _result_response(result)

@app.post("/ingest/news")
def ingest_news(
    query: str = Query(min_length=2, max_length=200),
    topic: Literal["news", "general"] = "news",
    days: int = Query(7, ge=1, le=365),
    max_results: int = Query(10, ge=1, le=20),
    refresh: bool = False,
):
    try:
        result = build_ingestor().ingest_news(
            query, topic=topic, days=days, max_results=max_results, refresh=refresh
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Ingestion failed") from exc
    return _result_response(result)
