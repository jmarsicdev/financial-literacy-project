import os
import psycopg2
from psycopg2.extras import execute_values
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col,
    lag,
    lead,
    when,
    avg,
    stddev_samp,
    max as spark_max,
    min as spark_min,
    count,
    round as spark_round,
    sqrt,
)
from pyspark.sql.window import Window


spark = (
    SparkSession.builder
    .appName("Sprint4-Gold-Features")
    .master("local[*]")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("WARN")

SILVER_PATH = "/opt/spark-app/output/silver/price_bars"
GOLD_PATH = "/opt/spark-app/output/gold/price_features"
SUMMARY_PATH = "/opt/spark-app/output/gold/sql_symbol_summary"

def persist_gold_metrics(summary_df):
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not configured")

    rows = [
        (
            row["symbol"],
            row["observations"],
            row["return_observations"],
            row["avg_daily_return_pct"],
            row["annualized_volatility_pct"],
            row["avg_20d_volatility_pct"],
            row["avg_daily_volume"],
            row["max_drawdown_pct"],
            row["next_day_up_pct"],
            row["first_date"],
            row["last_date"],
        )
        for row in summary_df.collect()
    ]

    if not rows:
        print("No Gold symbol metrics to persist.")
        return

    insert_sql = """
        INSERT INTO gold_symbol_metrics (
            symbol,
            observations,
            return_observations,
            avg_daily_return_pct,
            annualized_volatility_pct,
            avg_20d_volatility_pct,
            avg_daily_volume,
            max_drawdown_pct,
            next_day_up_pct,
            first_date,
            last_date,
            updated_at
        )
        VALUES %s
        ON CONFLICT (symbol) DO UPDATE SET
            observations = EXCLUDED.observations,
            return_observations = EXCLUDED.return_observations,
            avg_daily_return_pct = EXCLUDED.avg_daily_return_pct,
            annualized_volatility_pct = EXCLUDED.annualized_volatility_pct,
            avg_20d_volatility_pct = EXCLUDED.avg_20d_volatility_pct,
            avg_daily_volume = EXCLUDED.avg_daily_volume,
            max_drawdown_pct = EXCLUDED.max_drawdown_pct,
            next_day_up_pct = EXCLUDED.next_day_up_pct,
            first_date = EXCLUDED.first_date,
            last_date = EXCLUDED.last_date,
            updated_at = NOW()
    """

    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cursor:
            execute_values(
                cursor,
                insert_sql,
                rows,
                template=(
                    "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())"
                ),
            )

    print(f"Persisted {len(rows)} Gold symbol metrics to PostgreSQL.")

print("\n========== GOLD: FEATURE ENGINEERING ==========")

# Read the validated Silver dataset.
silver_df = spark.read.parquet(SILVER_PATH)

# Define windows separately for price history and rolling indicators.
history_window = (
    Window.partitionBy("symbol")
    .orderBy("bar_date")
)

rolling_5 = history_window.rowsBetween(-4, 0)
rolling_20 = history_window.rowsBetween(-19, 0)

# Running historical peak for drawdown calculations.
running_peak_window = (
    Window.partitionBy("symbol")
    .orderBy("bar_date")
    .rowsBetween(Window.unboundedPreceding, Window.currentRow)
)

# Calculate returns, rolling indicators, labels, and risk features.
features_df = (
    silver_df
    .withColumn(
        "previous_close",
        lag("adjusted_close", 1).over(history_window)
    )
    .withColumn(
        "daily_return",
        (col("adjusted_close") / col("previous_close")) - 1
    )
    .withColumn(
        "return_lag_1",
        lag("daily_return", 1).over(history_window)
    )
    .withColumn(
        "momentum_5d",
        (col("adjusted_close") /
         lag("adjusted_close", 5).over(history_window)) - 1
    )
    .withColumn("sma_5", avg("adjusted_close").over(rolling_5))
    .withColumn("sma_20", avg("adjusted_close").over(rolling_20))
    .withColumn(
        "volatility_20",
        stddev_samp("daily_return").over(rolling_20)
    )
    .withColumn(
        "running_peak",
        spark_max("adjusted_close").over(running_peak_window)
    )
    .withColumn(
        "drawdown",
        (col("adjusted_close") / col("running_peak")) - 1
    )
    .withColumn(
        "next_close",
        lead("adjusted_close", 1).over(history_window)
    )
    .withColumn(
        "next_day_up",
        when(col("next_close") > col("adjusted_close"), 1).otherwise(0)
    )
)

# Remove rows without a next trading day because they cannot be labeled.
# Keep initial rows with null rolling features; ML preparation handles them.
gold_df = (
    features_df
    .filter(col("next_close").isNotNull())
    .drop("previous_close", "next_close", "running_peak")
)

gold_count = gold_df.count()
silver_count = silver_df.count()

gold_df.write.mode("overwrite").partitionBy("symbol").parquet(GOLD_PATH)

print("Silver input records:", silver_count)
print("Gold labeled records:", gold_count)
print("Rows without a next trading day:", silver_count - gold_count)
print("Gold output:", GOLD_PATH)

print("\nGold records by symbol:")
gold_df.groupBy("symbol").count().orderBy("symbol").show(30, truncate=False)

# Register Gold data for SQL-based risk and performance analysis.
gold_df.createOrReplaceTempView("gold_price_features")

print("\n========== SPARK SQL: SYMBOL PERFORMANCE AND RISK SUMMARY ==========")

summary_df = spark.sql("""
    SELECT
        symbol,
        COUNT(*) AS observations,
        COUNT(daily_return) AS return_observations,
        ROUND(AVG(daily_return) * 100, 4) AS avg_daily_return_pct,
        ROUND(
            STDDEV_SAMP(daily_return) * SQRT(252) * 100,
            4
        ) AS annualized_volatility_pct,
        ROUND(AVG(volatility_20) * 100, 4) AS avg_20d_volatility_pct,
        ROUND(AVG(volume), 0) AS avg_daily_volume,
        ROUND(MIN(drawdown) * 100, 4) AS max_drawdown_pct,
        ROUND(AVG(next_day_up) * 100, 2) AS next_day_up_pct,
        MIN(bar_date) AS first_date,
        MAX(bar_date) AS last_date
    FROM gold_price_features
    GROUP BY symbol
    HAVING COUNT(daily_return) >= 2
    ORDER BY avg_daily_return_pct DESC
""")

summary_df.show(30, truncate=False)

summary_df.write.mode("overwrite").parquet(SUMMARY_PATH)
print("SQL summary output:", SUMMARY_PATH)

persist_gold_metrics(summary_df)

spark.stop()
print("\nGold feature engineering and Spark SQL completed successfully.")
