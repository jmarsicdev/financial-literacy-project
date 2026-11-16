CREATE TABLE IF NOT EXISTS gold_symbol_metrics (
    symbol TEXT PRIMARY KEY,
    observations BIGINT NOT NULL,
    return_observations BIGINT NOT NULL,
    avg_daily_return_pct DOUBLE PRECISION,
    annualized_volatility_pct DOUBLE PRECISION,
    avg_20d_volatility_pct DOUBLE PRECISION,
    avg_daily_volume DOUBLE PRECISION,
    max_drawdown_pct DOUBLE PRECISION,
    next_day_up_pct DOUBLE PRECISION,
    first_date DATE,
    last_date DATE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gold_symbol_metrics_updated
    ON gold_symbol_metrics(updated_at DESC);
