
import os
import json
import psycopg2

from pyspark.sql import SparkSession
from pyspark.sql.types import (
    StructType, StructField, LongType, StringType,
    TimestampType, DateType, DoubleType
)
from pyspark.sql.functions import col, row_number
from pyspark.sql.window import Window


# --------------------------------------------------
# 1. Spark session and PostgreSQL connection
# --------------------------------------------------

spark = (
    SparkSession.builder
    .appName("Sprint4-Bronze-Silver")
    .master("local[*]")
    .getOrCreate()
)

spark.sparkContext.setLogLevel("WARN")

DATABASE_URL = os.environ["DATABASE_URL"]
conn = psycopg2.connect(DATABASE_URL)

OUTPUT = "/opt/spark-app/output"


# --------------------------------------------------
# 2. BRONZE: Preserve raw ingestion records
# --------------------------------------------------

print("\n========== BRONZE: RAW PAYLOADS ==========")

with conn.cursor() as cur:
    cur.execute("""
        SELECT
            id,
            provider,
            endpoint,
            params::text,
            cache_key,
            payload::text,
            status,
            fetched_at
        FROM raw_payloads
        ORDER BY id
    """)
    raw_rows = cur.fetchall()

bronze_schema = StructType([
    StructField("id", LongType(), False),
    StructField("provider", StringType(), True),
    StructField("endpoint", StringType(), True),
    StructField("params_json", StringType(), True),
    StructField("cache_key", StringType(), True),
    StructField("payload_json", StringType(), True),
    StructField("status", StringType(), True),
    StructField("fetched_at", TimestampType(), True),
])

bronze_df = spark.createDataFrame(raw_rows, bronze_schema)

bronze_path = f"{OUTPUT}/bronze/raw_payloads"

bronze_df.write.mode("overwrite").parquet(bronze_path)

print("Bronze records:", bronze_df.count())
print("Bronze output:", bronze_path)

bronze_df.groupBy(
    "provider", "endpoint", "status"
).count().show(truncate=False)


# --------------------------------------------------
# 3. SILVER: Read normalized historical price bars
# --------------------------------------------------

print("\n========== SILVER: PRICE BARS ==========")

with conn.cursor() as cur:
    cur.execute("""
        SELECT
            symbol,
            bar_date,
            open,
            high,
            low,
            close,
            adjusted_close,
            volume,
            provider,
            updated_at
        FROM price_bars
        ORDER BY symbol, bar_date
    """)
    price_rows = cur.fetchall()

silver_schema = StructType([
    StructField("symbol", StringType(), False),
    StructField("bar_date", DateType(), False),
    StructField("open", DoubleType(), True),
    StructField("high", DoubleType(), True),
    StructField("low", DoubleType(), True),
    StructField("close", DoubleType(), True),
    StructField("adjusted_close", DoubleType(), True),
    StructField("volume", LongType(), True),
    StructField("provider", StringType(), True),
    StructField("updated_at", TimestampType(), True),
])

# Convert PostgreSQL Decimal values to Python floats.
silver_rows = [
    (
        symbol,
        bar_date,
        float(open_price) if open_price is not None else None,
        float(high) if high is not None else None,
        float(low) if low is not None else None,
        float(close) if close is not None else None,
        float(adjusted_close) if adjusted_close is not None else None,
        int(volume) if volume is not None else None,
        provider,
        updated_at
    )
    for (
        symbol, bar_date, open_price, high, low, close,
        adjusted_close, volume, provider, updated_at
    ) in price_rows
]

silver_raw = spark.createDataFrame(silver_rows, silver_schema)

input_count = silver_raw.count()

# Validate prices, volumes, and high/low relationships.
valid_df = silver_raw.filter(
    col("symbol").isNotNull()
    & col("bar_date").isNotNull()
    & col("adjusted_close").isNotNull()
    & (col("adjusted_close") > 0)
    & col("open").isNotNull()
    & col("high").isNotNull()
    & col("low").isNotNull()
    & col("close").isNotNull()
    & (col("open") >= 0)
    & (col("high") >= 0)
    & (col("low") >= 0)
    & (col("close") >= 0)
    & (col("high") >= col("low"))
    & col("volume").isNotNull()
    & (col("volume") >= 0)
)

# Remove duplicate symbol/date records, keeping latest update.
window = Window.partitionBy(
    "symbol", "bar_date"
).orderBy(col("updated_at").desc())

silver_df = (
    valid_df
    .withColumn("row_num", row_number().over(window))
    .filter(col("row_num") == 1)
    .drop("row_num")
)

output_count = silver_df.count()

silver_path = f"{OUTPUT}/silver/price_bars"

silver_df.write.mode("overwrite").partitionBy("symbol").parquet(
    silver_path
)

print("Silver input records:", input_count)
print("Silver valid, deduplicated records:", output_count)
print("Rejected records:", input_count - output_count)
print("Silver output:", silver_path)

print("\nSilver records by symbol:")
silver_df.groupBy("symbol").count().orderBy("symbol").show(30)

# --------------------------------------------------
# 4. Close connections
# --------------------------------------------------

conn.close()
spark.stop()

print("\nBronze and Silver pipeline completed successfully.")
