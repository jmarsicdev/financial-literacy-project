
import os
from datetime import date

from anyio import Path
import psycopg
from pyspark.sql import SparkSession

from backend.app.spark.gold import build_gold_features


def load_stock_prices():
    """Load recent AAPL and NVDA records from PostgreSQL."""

    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://team5:local_dev_only@localhost:5433/financial_literacy",
    )

    query = """
        WITH ranked_prices AS (
            SELECT
                symbol,
                bar_date,
                adjusted_close,
                volume,
                ROW_NUMBER() OVER (
                    PARTITION BY symbol
                    ORDER BY bar_date DESC
                ) AS row_num
            FROM price_bars
            WHERE symbol = ANY(%s)
        )
        SELECT symbol, bar_date, adjusted_close, volume
        FROM ranked_prices
        WHERE row_num <= 252
        ORDER BY symbol, bar_date
    """

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            symbols = [
            symbol.strip().upper()
            for symbol in os.getenv("GOLD_SYMBOLS", "AAPL,NVDA").split(",")
                if symbol.strip()
]

            if not symbols:
                raise ValueError("GOLD_SYMBOLS must contain at least one ticker")

            cursor.execute(query, (symbols,))
            return [
                (
                    row[0],
                    row[1],
                    float(row[2]),
                    int(row[3]),
                )
                for row in cursor.fetchall()
            ]


def main():
    spark = (
        SparkSession.builder
        .master("local[2]")
        .appName("FinancialLiteracyGoldLayer")
        .getOrCreate()
    )

    try:
        spark.sparkContext.setLogLevel("ERROR")

        records = load_stock_prices()
        print(f"Loaded {len(records)} price records")

        if not records:
            raise ValueError("No stock-price records found")

        silver_df = spark.createDataFrame(
            records,
            ["symbol", "bar_date", "adjusted_close", "volume"],
        )

        gold_df = build_gold_features(silver_df)

        print("\nGold Layer results:")
        gold_df.show(truncate=False)

        print("Gold records:", gold_df.count())

        from pathlib import Path

        output_dir = Path("data/gold")
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / "stock_risk_features.csv"

        gold_df.toPandas().to_csv(output_file, index=False)

        print(f"Gold features exported to: {output_file}")

    finally:
        spark.stop()


if __name__ == "__main__":
    main()
