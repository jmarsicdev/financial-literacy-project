-- for db volumes created before raw_payloads was in init.sql (fresh volumes don't need this)
-- docker compose exec -T db psql -U team5 -d financial_literacy < backend/sql/migrations/001_raw_payloads.sql
CREATE TABLE IF NOT EXISTS raw_payloads (
  id BIGSERIAL PRIMARY KEY,
  provider VARCHAR(40) NOT NULL,
  endpoint VARCHAR(80) NOT NULL,
  params JSONB NOT NULL DEFAULT '{}'::jsonb,
  cache_key TEXT NOT NULL,
  payload JSONB NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'ok',
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_raw_payloads_lookup ON raw_payloads(provider, cache_key, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_payloads_provider_time ON raw_payloads(provider, fetched_at);
