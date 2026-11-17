# read side of the Spark risk-profile clustering (spark/jobs/cluster_risk_profiles.py writes the table)
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query
from psycopg.rows import dict_row

from .db import get_connection

router = APIRouter(prefix="/risk-profiles", tags=["Risk Profiles"])

DISCLAIMER = (
    "A historical risk profile describes how a security's price behaved in a past quarter relative to "
    "the other securities in this project's dataset. It is not a forecast and not investment advice."
)

_COLUMNS = (
    "symbol, quarter_start, risk_profile, profile_rank, profile_count, annualized_volatility, max_drawdown, "
    "beta_vs_benchmark, avg_intraday_range, return_observations, asset_type, sector, benchmark, data_split, "
    "train_silhouette, test_silhouette, updated_at"
)


def get_symbol_profile(symbol: str, history: int = 8) -> dict[str, Any] | None:
    """Latest quarter, share of quarters spent in each profile, and recent history for one symbol."""
    symbol = symbol.strip().upper()
    with get_connection() as conn:
        conn.row_factory = dict_row
        recent = conn.execute(
            f"SELECT {_COLUMNS} FROM risk_profiles WHERE symbol = %s ORDER BY quarter_start DESC LIMIT %s",
            (symbol, history),
        ).fetchall()
        if not recent:
            return None
        mix = conn.execute(
            "SELECT risk_profile, profile_rank, count(*) AS quarters, min(quarter_start) AS first_quarter "
            "FROM risk_profiles WHERE symbol = %s GROUP BY risk_profile, profile_rank ORDER BY profile_rank",
            (symbol,),
        ).fetchall()

    total = sum(int(row["quarters"]) for row in mix) or 1
    return {
        "symbol": symbol,
        "latest": recent[0],
        "quarters_total": total,
        "first_quarter": min(row["first_quarter"] for row in mix),
        "profile_mix": [
            {
                "risk_profile": row["risk_profile"],
                "profile_rank": row["profile_rank"],
                "quarters": int(row["quarters"]),
                "pct_of_quarters": round(100.0 * int(row["quarters"]) / total, 1),
            }
            for row in mix
        ],
        "history": recent,
        "disclaimer": DISCLAIMER,
    }


def list_latest_profiles(limit: int = 100) -> list[dict[str, Any]]:
    """Most recent complete quarter for every symbol."""
    with get_connection() as conn:
        conn.row_factory = dict_row
        return conn.execute(
            f"SELECT DISTINCT ON (symbol) {_COLUMNS} FROM risk_profiles "
            "ORDER BY symbol, quarter_start DESC LIMIT %s",
            (limit,),
        ).fetchall()


@router.get("")
def list_risk_profiles(limit: int = Query(default=100, ge=1, le=500)):
    try:
        items = list_latest_profiles(limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Risk profiles are unavailable") from exc
    return {"count": len(items), "items": items, "disclaimer": DISCLAIMER}


@router.get("/{symbol}")
def get_risk_profile(symbol: str = Path(min_length=1, max_length=15), history: int = Query(default=8, ge=1, le=200)):
    try:
        profile = get_symbol_profile(symbol, history)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Risk profiles are unavailable") from exc
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"No risk profile for {symbol.strip().upper()}. Run the Spark clustering job after loading its prices.",
        )
    return profile
