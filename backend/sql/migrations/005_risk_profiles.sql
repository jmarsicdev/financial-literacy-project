-- historical risk profiles written by spark/jobs/cluster_risk_profiles.py (one row per symbol per quarter)
-- existing volumes: docker compose exec -T db psql -U team5 -d financial_literacy < backend/sql/migrations/005_risk_profiles.sql
CREATE TABLE IF NOT EXISTS risk_profiles (
    symbol TEXT NOT NULL,
    quarter_start DATE NOT NULL,
    risk_profile TEXT NOT NULL,
    profile_rank INTEGER NOT NULL,
    profile_count INTEGER NOT NULL,
    annualized_volatility DOUBLE PRECISION NOT NULL,
    max_drawdown DOUBLE PRECISION NOT NULL,
    beta_vs_benchmark DOUBLE PRECISION NOT NULL,
    avg_intraday_range DOUBLE PRECISION NOT NULL,
    return_observations BIGINT NOT NULL,
    asset_type TEXT,
    sector TEXT,
    benchmark TEXT NOT NULL,
    data_split TEXT NOT NULL,
    train_silhouette DOUBLE PRECISION,
    test_silhouette DOUBLE PRECISION,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, quarter_start)
);

CREATE INDEX IF NOT EXISTS idx_risk_profiles_quarter ON risk_profiles(quarter_start DESC);
