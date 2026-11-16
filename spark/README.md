# Sprint 4 — Apache Spark Data Pipeline and Machine Learning

## Overview

This module implements the Sprint 4 data engineering and machine learning workflow using Apache Spark and PySpark.

It reads historical market data from the project's PostgreSQL database, processes it through Bronze, Silver, and Gold layers, performs Spark SQL analysis, and trains two machine learning models to classify whether a stock's adjusted closing price increases on the next trading day.

Spark runs in a separate Docker service and does not replace or modify the existing FastAPI, React, PostgreSQL, or Redis services.

## Technology Stack

| Component | Version / Technology |
|---|---|
| Python | 3.11 |
| Java | OpenJDK 17 |
| Apache Spark | 3.5.7 |
| PySpark | 3.5.7 |
| NumPy | 1.26.4 |
| PostgreSQL driver | psycopg2-binary 2.9.10 |
| Storage format | Apache Parquet |
| Machine learning | Spark MLlib |

Spark runs in local mode using `local[*]` inside its Docker container.

## Architecture

The workflow is:

1. PostgreSQL provides raw ingestion payloads and normalized historical price bars.
2. Spark reads the source data and creates the Bronze layer.
3. Spark validates, cleans, and deduplicates price records to create the Silver layer.
4. Spark calculates historical features and next-trading-day labels to create the Gold layer.
5. Spark SQL produces a summary of historical price performance by symbol.
6. Spark MLlib trains Logistic Regression and Random Forest models.
7. Test predictions and trained models are saved as Parquet and Spark model artifacts.

### Data layers

| Layer | Input | Output |
|---|---|---|
| Bronze | PostgreSQL `raw_payloads` | Raw payload Parquet |
| Silver | PostgreSQL `price_bars` | Validated and deduplicated price Parquet |
| Gold | Silver price data | Feature-engineered and labeled Parquet |

## Prerequisites

- Docker Desktop running.
- Docker Compose available.
- Project environment configured with the required database settings.
- Historical price data available in PostgreSQL.

## Running the Pipeline

Run commands from the repository root.

### 1. Start the required services

```powershell
docker compose up -d db backend redis spark
```

### 2. Ingest historical price data

If the database does not already contain historical price data:

```powershell
docker compose exec backend python -m app.ingestion seed-prices
```

Check ingestion status:

```powershell
docker compose exec backend python -m app.ingestion status
```

### 3. Run Bronze and Silver processing

```powershell
docker compose exec spark spark-submit jobs/bronze_silver.py
```

This job:
- Reads raw provider payloads from PostgreSQL into Bronze.
- Reads historical price bars into Silver.
- Validates price and volume fields.
- Removes invalid records.
- Deduplicates records by symbol and trading date.
- Writes Parquet output.

### 4. Generate Gold features and Spark SQL summary

```powershell
docker compose exec spark spark-submit jobs/gold_features.py
```

This job calculates:
- Daily return.
- Previous-day return.
- Five-day momentum.
- Five-day moving average.
- Twenty-day moving average.
- Twenty-day volatility.
- Next-trading-day price direction label.

It also generates a Spark SQL summary grouped by symbol.

### 5. Train Logistic Regression

```powershell
docker compose exec spark spark-submit jobs/train_model.py
```

The job:
- Uses six historical features.
- Applies VectorAssembler and StandardScaler.
- Trains a Logistic Regression classifier.
- Evaluates predictions on a chronological test set.
- Saves the model and test predictions.

### 6. Train Random Forest

```powershell
docker compose exec spark spark-submit jobs/train_random_forest.py
```

The job:
- Uses the same six features and chronological split.
- Trains a Random Forest classifier.
- Calculates evaluation metrics and feature importance.
- Saves the model and test predictions.

## Generated Output

All generated files are stored under `spark/output/`.

| Output | Location |
|---|---|
| Bronze raw payloads | `spark/output/bronze/raw_payloads` |
| Silver price bars | `spark/output/silver/price_bars` |
| Gold features | `spark/output/gold/price_features` |
| Spark SQL summary | `spark/output/gold/sql_symbol_summary` |
| Logistic Regression model | `spark/output/models/logistic_regression` |
| Logistic Regression predictions | `spark/output/predictions/test_predictions` |
| Random Forest model | `spark/output/models/random_forest` |
| Random Forest predictions | `spark/output/predictions/random_forest_predictions` |

The output directory is excluded from Git because it contains generated Parquet files, model artifacts, and predictions. Run the pipeline to regenerate these outputs.

## Dataset and Processing Results

The completed pipeline processed historical data for 19 symbols.

| Processing stage | Records |
|---|---:|
| Bronze raw payloads | 20 |
| Silver input price bars | 119,956 |
| Silver valid and deduplicated records | 119,956 |
| Rejected Silver records | 0 |
| Gold labeled records | 119,937 |
| Gold rows without a next trading day | 19 |
| Gold usable ML records after feature filtering | 119,842 |
| Training records | 78,550 |
| Testing records | 41,277 |

The 19 Gold records excluded from labeling are the final available trading-day observations for each symbol because no subsequent trading day is available to calculate the label.

The chronological test period begins on **July 7, 2017**.

## Machine Learning Methodology

### Prediction objective

The classification target is:

- `1`: The next trading day's adjusted closing price is higher than the current adjusted closing price.
- `0`: The next trading day's adjusted closing price is not higher than the current adjusted closing price.

### Features

Both models use the following six features:

1. `daily_return`
2. `return_lag_1`
3. `momentum_5d`
4. `sma_5_gap`
5. `sma_20_gap`
6. `volatility_20`

The moving-average gap features represent the adjusted closing price relative to the five-day and twenty-day moving averages.

### Avoiding data leakage

The feature calculations use current and historical price observations only.

The Spark `lead()` operation is used to generate the next-trading-day target label. The future closing price is not included as a model feature.

The dataset is split chronologically rather than randomly. Training records whose next trading-day target crosses the training/test boundary are excluded from training.

This helps prevent future information from leaking into the training dataset.

## Model Evaluation

The following results were obtained from the completed test runs.

| Metric | Logistic Regression | Random Forest |
|---|---:|---:|
| Accuracy | 52.84% | 52.33% |
| Precision | 54.33% | 55.01% |
| Recall | 73.22% | 58.87% |
| Weighted F1 | 50.47% | 52.14% |
| ROC AUC | 51.99% | 52.55% |

The test set contains 22,039 positive labels out of 41,277 records. An always-positive baseline therefore achieves approximately **53.39% accuracy**.

Both models have ROC AUC values close to 0.50, indicating limited predictive discrimination on this test set. Neither model demonstrates strong predictive performance.

Logistic Regression has higher recall, while Random Forest has slightly higher precision, weighted F1, and ROC AUC.

### Random Forest feature importance

| Feature | Importance |
|---|---:|
| volatility_20 | 0.197423 |
| daily_return | 0.166940 |
| sma_20_gap | 0.165647 |
| sma_5_gap | 0.156835 |
| return_lag_1 | 0.156826 |
| momentum_5d | 0.156329 |

## Important Notes

- This is an educational machine learning demonstration.
- The models are not investment recommendations or financial advice.
- Historical price patterns do not guarantee future performance.
- The evaluation results do not establish that either model can reliably predict future stock prices.
- Spark is currently configured for local execution in a single container, not a distributed multi-node cluster.

## Reproducibility

Run the jobs in the following order:

1. `bronze_silver.py`
2. `gold_features.py`
3. `train_model.py`
4. `train_random_forest.py`

Ensure the database has historical price data before running the pipeline.

Generated outputs are not committed to Git. The source code and configuration files are sufficient to regenerate them.
