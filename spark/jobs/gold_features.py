
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

spark.stop()
print("\nGold feature engineering and Spark SQL completed successfully.")
