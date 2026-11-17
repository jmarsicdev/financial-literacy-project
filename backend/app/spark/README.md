# Spark SQL Gold Layer

## Overview

This module generates historical stock-risk features for the
Financial Literacy Service project.

The Gold Layer is intended to provide aggregated stock features
for downstream Spark ML clustering.

## Where it runs

`build_gold_features` in `gold.py` is the single implementation of the per-symbol risk summary.
`spark/jobs/gold_features.py` calls it on the Silver price data for every symbol, formats the result with
Spark SQL, and writes it to Parquet and to the `gold_symbol_metrics` table served by `GET /spark/gold/metrics`.

Required Silver columns:

- symbol
- bar_date
- adjusted_close
- volume

## Gold Features

- avg_daily_return: Average daily percentage change, expressed as a decimal.
- annualized_volatility: Standard deviation of daily returns multiplied by sqrt(252).
- avg_daily_volume: Average daily trading volume.
- max_drawdown: Largest decline from a running historical price peak.
- trading_days: Number of historical price observations.
- return_observations: Number of valid daily returns.

The output also includes the stock symbol and date range.

## Run

The function runs as part of the Spark pipeline (see `spark/README.md`):

docker compose exec spark spark-submit jobs/bronze_silver.py

docker compose exec spark spark-submit jobs/gold_features.py

The earlier standalone runner (`run_gold.py`, two symbols to CSV) was removed once the pipeline job
covered every symbol.

## Testing

Run:

python -m pytest spark/tests/test_spark_gold.py -v

The test lives under `spark/tests` because it needs PySpark and Java, which the backend image does not install.
Inside Docker: `docker compose exec spark python -m pytest tests -v`.

The current suite includes six tests covering calculations,
record counts, missing columns, duplicates, invalid prices,
and insufficient historical observations.

## Limitations

- Figures cover each symbol's full stored history, so symbols with longer histories are not directly comparable to recent listings.
- The Gold features must be regenerated when the source data changes.
