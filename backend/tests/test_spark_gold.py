
from datetime import date
from pyspark.sql import functions as F

import pytest
from pyspark.sql import SparkSession

from backend.app.spark.gold import build_gold_features


@pytest.fixture(scope="module")
def spark():
    session = (
        SparkSession.builder
        .master("local[2]")
        .appName("GoldLayerPytest")
        .getOrCreate()
    )
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


@pytest.fixture
def sample_data(spark):
    data = [
        ("AAPL", date(2026, 1, 5), 100.0, 1000000),
        ("AAPL", date(2026, 1, 6), 105.0, 1200000),
        ("AAPL", date(2026, 1, 7), 102.0, 1100000),
        ("AAPL", date(2026, 1, 8), 108.0, 1300000),
        ("NVDA", date(2026, 1, 5), 200.0, 2000000),
        ("NVDA", date(2026, 1, 6), 210.0, 2200000),
        ("NVDA", date(2026, 1, 7), 190.0, 2100000),
        ("NVDA", date(2026, 1, 8), 205.0, 2300000),
    ]

    return spark.createDataFrame(
        data,
        ["symbol", "bar_date", "adjusted_close", "volume"],
    )


def test_gold_record_count(sample_data):
    gold = build_gold_features(sample_data)
    assert gold.count() == 2


def test_gold_features(sample_data):
    gold = build_gold_features(sample_data)
    rows = {row["symbol"]: row for row in gold.collect()}

    assert rows["AAPL"]["trading_days"] == 4
    assert rows["NVDA"]["trading_days"] == 4

    assert rows["AAPL"]["return_observations"] == 3
    assert rows["NVDA"]["return_observations"] == 3

    assert rows["AAPL"]["avg_daily_volume"] == pytest.approx(
        1150000.0
    )

    assert rows["NVDA"]["avg_daily_volume"] == pytest.approx(
        2150000.0
    )

    assert rows["AAPL"]["max_drawdown"] == pytest.approx(
        -0.02857142857142858
    )

    assert rows["NVDA"]["max_drawdown"] == pytest.approx(
        -0.09523809523809523
    )

    assert rows["AAPL"]["annualized_volatility"] == pytest.approx(
        0.7637712452538519
    )

    assert rows["NVDA"]["annualized_volatility"] == pytest.approx(
        1.4817052568834175
    )


def test_missing_required_column(sample_data):
    invalid = sample_data.drop("adjusted_close")

    with pytest.raises(ValueError, match="Missing Silver columns"):
        build_gold_features(invalid)


def test_duplicate_records(sample_data):
    duplicate = sample_data.unionByName(sample_data.limit(1))

    with pytest.raises(ValueError, match="Duplicate symbol/date"):
        build_gold_features(duplicate)



def test_invalid_price(sample_data):
    invalid = sample_data.withColumn(
        "adjusted_close",
        -F.abs(F.col("adjusted_close")),
    )

    with pytest.raises(ValueError, match="invalid stock records"):
        build_gold_features(invalid)



def test_insufficient_history(spark):
    data = [
        ("AAPL", date(2026, 1, 5), 100.0, 1000000),
        ("AAPL", date(2026, 1, 6), 105.0, 1100000),
    ]

    silver = spark.createDataFrame(
        data,
        ["symbol", "bar_date", "adjusted_close", "volume"],
    )

    gold = build_gold_features(silver)

    assert gold.count() == 0
