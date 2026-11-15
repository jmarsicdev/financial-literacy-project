# Spark SQL Gold Layer

## Overview

This module generates historical stock-risk features for the
Financial Literacy Service project.

The Gold Layer is intended to provide aggregated stock features
for downstream Spark ML clustering.

## Data Source

The current integration runner reads stock prices from the
PostgreSQL `price_bars` table.

Required columns:

- symbol
- bar_date
- adjusted_close
- volume

The current runner processes the latest 252 observations
for AAPL and NVDA.

## Gold Features

- avg_daily_return: Average daily percentage change, expressed as a decimal.
- annualized_volatility: Standard deviation of daily returns multiplied by sqrt(252).
- avg_daily_volume: Average daily trading volume.
- max_drawdown: Largest decline from a running historical price peak.
- trading_days: Number of historical price observations.
- return_observations: Number of valid daily returns.

The output also includes the stock symbol and date range.

## Run Locally

Requirements:

- Python 3.11
- PySpark 3.5.0
- PostgreSQL with stock-price records
- psycopg

Start PostgreSQL:

docker compose up -d db

Set DATABASE_URL to a valid PostgreSQL connection string.

Run from the repository root:

python -m backend.app.spark.run_gold

The script exports:

data/gold/stock_risk_features.csv

### Selecting Stocks

By default, the runner processes AAPL and NVDA using the latest
252 historical price observations per stock.

To select different stocks in PowerShell:

$env:GOLD_SYMBOLS = "AAPL,NVDA,MSFT"

Only stocks available in the PostgreSQL database will be processed.

## Testing

Run:

python -m pytest backend/tests/test_spark_gold.py -v

The current suite includes six tests covering calculations,
record counts, missing columns, duplicates, invalid prices,
and insufficient historical observations.

## Limitations

- The current runner is configured for AAPL and NVDA only.
- It uses a local PostgreSQL source, not the team's finalized Silver dataset.
- The CSV export is intended for integration testing.
- Two stocks are insufficient for meaningful ML clustering.
- The Gold features must be regenerated when the source data changes.
