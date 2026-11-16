
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F


REQUIRED_COLUMNS = {
    "symbol",
    "bar_date",
    "adjusted_close",
    "volume",
}


def build_gold_features(silver_df: DataFrame) -> DataFrame:
    """Build historical stock-risk features from cleaned Silver data."""

    missing = REQUIRED_COLUMNS - set(silver_df.columns)
    if missing:
        raise ValueError(f"Missing Silver columns: {sorted(missing)}")

    # Normalize column types before calculations.
    prices = silver_df.select(
        F.upper(F.trim(F.col("symbol"))).alias("symbol"),
        F.to_date("bar_date").alias("bar_date"),
        F.col("adjusted_close").cast("double").alias("adjusted_close"),
        F.col("volume").cast("long").alias("volume"),
    )

    # Validate input instead of silently dropping incorrect records.
    invalid = prices.filter(
        F.col("symbol").isNull()
        | (F.col("symbol") == "")
        | F.col("bar_date").isNull()
        | F.col("adjusted_close").isNull()
        | F.isnan("adjusted_close")
        | (F.col("adjusted_close") <= 0)
        | F.col("volume").isNull()
        | (F.col("volume") < 0)
    )

    if invalid.limit(1).count():
        raise ValueError("Silver data contains invalid stock records")

    duplicates = (
        prices.groupBy("symbol", "bar_date")
        .count()
        .filter(F.col("count") > 1)
    )

    if duplicates.limit(1).count():
        raise ValueError("Duplicate symbol/date records found")

    # Order historical prices by stock and trading date.
    stock_window = Window.partitionBy("symbol").orderBy("bar_date")

    history_window = stock_window.rowsBetween(
        Window.unboundedPreceding,
        Window.currentRow,
    )

    # Get the previous day's adjusted closing price.
    prices = prices.withColumn(
        "previous_close",
        F.lag("adjusted_close").over(stock_window),
    )

    # Calculate daily returns.
    prices = prices.withColumn(
        "daily_return",
        (F.col("adjusted_close") / F.col("previous_close")) - 1.0,
    )

    # Calculate the running historical price peak.
    prices = prices.withColumn(
        "running_peak",
        F.max("adjusted_close").over(history_window),
    )

    # Calculate drawdown from the running peak.
    prices = prices.withColumn(
        "drawdown",
        (F.col("adjusted_close") / F.col("running_peak")) - 1.0,
    )

    # Register the DataFrame as a Spark SQL temporary view.
    prices.createOrReplaceTempView("gold_daily_prices")

    # Aggregate daily data into one row per stock.
    gold_df = prices.sparkSession.sql("""
        SELECT
            symbol,
            MIN(bar_date) AS start_date,
            MAX(bar_date) AS end_date,
            COUNT(*) AS trading_days,
            COUNT(daily_return) AS return_observations,
            AVG(daily_return) AS avg_daily_return,
            STDDEV_SAMP(daily_return) * SQRT(252.0)
                AS annualized_volatility,
            AVG(volume) AS avg_daily_volume,
            MIN(drawdown) AS max_drawdown
        FROM gold_daily_prices
        GROUP BY symbol
        HAVING COUNT(daily_return) >= 2
    """)

    return gold_df.orderBy("symbol")
