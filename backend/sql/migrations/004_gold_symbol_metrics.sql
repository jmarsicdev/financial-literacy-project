-- per-symbol historical risk summary written by spark/jobs/gold_features.py
-- existing volumes: docker compose exec -T db psql -U team5 -d financial_literacy < backend/sql/migrations/004_gold_symbol_metrics.sql
CREATE TABLE IF NOT EXISTS gold_symbol_metrics (
    symbol TEXT PRIMARY KEY,
    observations BIGINT NOT NULL,
    return_observations BIGINT NOT NULL,
    avg_daily_return_pct DOUBLE PRECISION,
    annualized_volatility_pct DOUBLE PRECISION,
    avg_20d_volatility_pct DOUBLE PRECISION,
    avg_daily_volume DOUBLE PRECISION,
    max_drawdown_pct DOUBLE PRECISION,
    first_date DATE,
    last_date DATE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gold_symbol_metrics_updated
    ON gold_symbol_metrics(updated_at DESC);

-- an earlier draft stored the share of days followed by an up day; it reads as a prediction, so it is not kept
ALTER TABLE gold_symbol_metrics DROP COLUMN IF EXISTS next_day_up_pct;
