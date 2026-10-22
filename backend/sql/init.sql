CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS ticker_metadata (
  symbol VARCHAR(15) PRIMARY KEY, company_name TEXT, sector TEXT, industry TEXT,
  exchange TEXT, market_cap BIGINT, business_summary TEXT, provider TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS price_bars (
  symbol VARCHAR(15) NOT NULL, bar_date DATE NOT NULL,
  open NUMERIC(18,6) NOT NULL CHECK(open >= 0), high NUMERIC(18,6) NOT NULL CHECK(high >= 0),
  low NUMERIC(18,6) NOT NULL CHECK(low >= 0), close NUMERIC(18,6) NOT NULL CHECK(close >= 0),
  adjusted_close NUMERIC(18,6) NOT NULL CHECK(adjusted_close >= 0),
  volume BIGINT NOT NULL CHECK(volume >= 0), provider VARCHAR(40) NOT NULL DEFAULT 'unknown',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(symbol, bar_date), CHECK(high >= low)
);
CREATE INDEX IF NOT EXISTS idx_price_bars_date ON price_bars(bar_date DESC);
CREATE TABLE IF NOT EXISTS search_results (
  id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, url TEXT, normalized_url TEXT UNIQUE,
  content TEXT, raw_content TEXT, source_domain TEXT, score NUMERIC(5,4),
  published_at TIMESTAMPTZ, query_text TEXT, provider VARCHAR(40) NOT NULL DEFAULT 'tavily',
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS events (
  id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, url TEXT, event_date DATE NOT NULL,
  symbol VARCHAR(15), source_domain TEXT, window_return NUMERIC(12,6),
  benchmark_return NUMERIC(12,6), abnormal_return NUMERIC(12,6),
  is_significant BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_symbol_date ON events(symbol, event_date);
CREATE TABLE IF NOT EXISTS user_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), confidence_level VARCHAR(30),
  financial_interests TEXT[] NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS search_history (
  id BIGSERIAL PRIMARY KEY, user_id UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
  query_text TEXT NOT NULL, searched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS document_chunks (
  id BIGSERIAL PRIMARY KEY, source_url TEXT, title TEXT, chunk_text TEXT NOT NULL,
  chunk_index INTEGER NOT NULL DEFAULT 0, metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  embedding vector(1536), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(source_url, chunk_index)
);

-- raw api responses, one row per call incl. failures
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
