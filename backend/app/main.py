import os
import redis
from datetime import date
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from psycopg.rows import dict_row
from .db import get_connection

app = FastAPI(title="Team 5 Financial Literacy API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=False, allow_methods=["*"], allow_headers=["*"]
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

def cache():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)

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
