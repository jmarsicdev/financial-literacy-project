# Historical risk profiles: one row per symbol per quarter, clustered with KMeans.
# Descriptive, not predictive: a profile says how a stock behaved in a past quarter, nothing about future prices.
#
# bronze/raw_payloads --(parse yfinance info)--> silver/ticker_metadata
# silver/price_bars + SPY benchmark returns + metadata --> gold/risk_profile_features --> KMeans
import os

from pyspark.ml import Pipeline
from pyspark.ml.clustering import KMeans
from pyspark.ml.evaluation import ClusteringEvaluator
from pyspark.ml.feature import StandardScaler, VectorAssembler
from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F

OUTPUT = os.getenv("SPARK_OUTPUT", "/opt/spark-app/output")
BRONZE_PATH = f"{OUTPUT}/bronze/raw_payloads"
SILVER_PRICES = f"{OUTPUT}/silver/price_bars"
SILVER_METADATA = f"{OUTPUT}/silver/ticker_metadata"
GOLD_PATH = f"{OUTPUT}/gold/risk_profile_features"
MODEL_PATH = f"{OUTPUT}/models/risk_profile_kmeans"
ASSIGNMENT_PATH = f"{OUTPUT}/predictions/risk_profiles"

BENCHMARK = os.getenv("RISK_BENCHMARK", "SPY")
MIN_RETURNS_PER_QUARTER = 40
K_CANDIDATES = [2, 3, 4, 5, 6]
SEED = 42
FEATURES = ["annualized_volatility", "max_drawdown", "beta_vs_benchmark", "avg_intraday_range"]

spark = (
    SparkSession.builder
    .appName("Sprint4-Risk-Profile-Clustering")
    .master("local[*]")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("WARN")


# --------------------------------------------------
# 1. SILVER: ticker metadata parsed from Bronze payloads
# --------------------------------------------------

print("\n========== SILVER: TICKER METADATA FROM BRONZE ==========")

bronze = spark.read.parquet(BRONZE_PATH)

info = (
    bronze
    .filter((F.col("provider") == "yfinance") & (F.col("endpoint") == "info") & (F.col("status") == "ok"))
    .select(
        F.upper(F.get_json_object("params_json", "$.symbol")).alias("symbol"),
        F.get_json_object("payload_json", "$.longName").alias("company_name"),
        F.get_json_object("payload_json", "$.quoteType").alias("asset_type"),
        F.get_json_object("payload_json", "$.sector").alias("sector"),
        "fetched_at",
    )
    .filter(F.col("symbol").isNotNull())
)

latest = Window.partitionBy("symbol").orderBy(F.col("fetched_at").desc())
metadata = (
    info.withColumn("rn", F.row_number().over(latest))
    .filter(F.col("rn") == 1)
    .drop("rn", "fetched_at")
    .withColumn("asset_type", F.coalesce("asset_type", F.lit("UNKNOWN")))
)
metadata.write.mode("overwrite").parquet(SILVER_METADATA)

print("Bronze records read:", bronze.count())
print("Silver ticker metadata records:", metadata.count())
print("Silver output:", SILVER_METADATA)


# --------------------------------------------------
# 2. GOLD: join prices to the benchmark and aggregate per symbol-quarter
# --------------------------------------------------

print("\n========== GOLD: QUARTERLY RISK FEATURES ==========")

prices = spark.read.parquet(SILVER_PRICES)
by_symbol = Window.partitionBy("symbol").orderBy("bar_date")

daily = (
    prices
    .withColumn("daily_return", F.col("adjusted_close") / F.lag("adjusted_close").over(by_symbol) - 1)
    .withColumn("quarter_start", F.date_trunc("quarter", F.col("bar_date")).cast("date"))
    .withColumn(
        "intraday_range",
        F.when(F.col("close") > 0, (F.col("high") - F.col("low")) / F.col("close")),
    )
)

benchmark = (
    daily.filter(F.col("symbol") == BENCHMARK)
    .select("bar_date", F.col("daily_return").alias("benchmark_return"))
)
if benchmark.limit(1).count() == 0:
    raise ValueError(f"Benchmark {BENCHMARK} has no price history in Silver")

# drawdown inside the quarter: fall from the highest close seen so far in that quarter
in_quarter = (
    Window.partitionBy("symbol", "quarter_start").orderBy("bar_date")
    .rowsBetween(Window.unboundedPreceding, Window.currentRow)
)

joined = (
    daily.join(benchmark, on="bar_date", how="left")
    .withColumn("quarter_peak", F.max("adjusted_close").over(in_quarter))
    .withColumn("quarter_drawdown", F.col("adjusted_close") / F.col("quarter_peak") - 1)
)
joined.createOrReplaceTempView("daily_with_benchmark")
metadata.createOrReplaceTempView("ticker_metadata")

gold = spark.sql(f"""
    SELECT
        d.symbol,
        d.quarter_start,
        COALESCE(m.asset_type, 'UNKNOWN') AS asset_type,
        m.sector,
        COUNT(d.daily_return) AS return_observations,
        STDDEV_SAMP(d.daily_return) * SQRT(252.0) AS annualized_volatility,
        MIN(d.quarter_drawdown) AS max_drawdown,
        COVAR_SAMP(d.daily_return, d.benchmark_return)
            / VAR_SAMP(d.benchmark_return) AS beta_vs_benchmark,
        AVG(d.intraday_range) AS avg_intraday_range
    FROM daily_with_benchmark d
    LEFT JOIN ticker_metadata m ON m.symbol = d.symbol
    GROUP BY d.symbol, d.quarter_start, m.asset_type, m.sector
    HAVING COUNT(d.daily_return) >= {MIN_RETURNS_PER_QUARTER}
""")

complete = gold
for feature in FEATURES:
    complete = complete.filter(F.col(feature).isNotNull() & ~F.isnan(feature))
complete = complete.cache()

daily_count = daily.count()
gold_count = gold.count()
usable_count = complete.count()

complete.write.mode("overwrite").parquet(GOLD_PATH)

print("Silver daily price records:", daily_count)
print(f"Symbol-quarters with at least {MIN_RETURNS_PER_QUARTER} returns:", gold_count)
print("Usable symbol-quarters (all features present):", usable_count)
print(f"Dropped (no {BENCHMARK} history for the quarter or missing values):", gold_count - usable_count)
print("Gold output:", GOLD_PATH)


# --------------------------------------------------
# 3. Chronological train/test split by quarter
# --------------------------------------------------

print("\n========== TRAIN/TEST SPLIT ==========")

quarters = [r["quarter_start"] for r in complete.select("quarter_start").distinct().orderBy("quarter_start").collect()]
test_start = quarters[int(len(quarters) * 0.80)]

train = complete.filter(F.col("quarter_start") < test_start).cache()
test = complete.filter(F.col("quarter_start") >= test_start).cache()
train_count, test_count = train.count(), test.count()

print("Test period starts:", test_start)
print("Training symbol-quarters:", train_count)
print("Testing symbol-quarters:", test_count)
if train_count == 0 or test_count == 0:
    raise ValueError("Training or testing dataset is empty.")


# --------------------------------------------------
# 4. Choose k by silhouette on the training set
# --------------------------------------------------

print("\n========== SPARK ML: KMEANS MODEL SELECTION ==========")

evaluator = ClusteringEvaluator(featuresCol="features", predictionCol="prediction", metricName="silhouette")


def build_pipeline(k: int) -> Pipeline:
    return Pipeline(stages=[
        VectorAssembler(inputCols=FEATURES, outputCol="raw_features", handleInvalid="error"),
        StandardScaler(inputCol="raw_features", outputCol="features", withMean=True, withStd=True),
        KMeans(featuresCol="features", predictionCol="prediction", k=k, seed=SEED, maxIter=50),
    ])


scores = []
models = {}
for k in K_CANDIDATES:
    fitted = build_pipeline(k).fit(train)
    models[k] = fitted
    train_score = evaluator.evaluate(fitted.transform(train))
    test_score = evaluator.evaluate(fitted.transform(test))
    scores.append((k, train_score, test_score))
    print(f"k={k}: train silhouette {train_score:.4f}, test silhouette {test_score:.4f}")

best_k, best_train, best_test = max(scores, key=lambda item: item[1])
model = models[best_k]

print(f"\nSelected k={best_k} (highest training silhouette)")
print(f"Training silhouette: {best_train:.4f}")
print(f"Test silhouette:     {best_test:.4f}")


# --------------------------------------------------
# 5. Name clusters in order of average volatility (the label covers all four features) and assign every symbol-quarter
# --------------------------------------------------

assigned = model.transform(complete).withColumn(
    "split", F.when(F.col("quarter_start") >= test_start, "test").otherwise("train")
)

order = [
    r["prediction"]
    for r in assigned.groupBy("prediction").agg(F.avg("annualized_volatility").alias("v")).orderBy("v").collect()
]
if best_k == 2:
    names = ["lower historical variability", "higher historical variability"]
elif best_k == 3:
    names = ["lower historical variability", "moderate historical variability", "higher historical variability"]
else:
    names = [f"variability level {i + 1} of {best_k}" for i in range(best_k)]

label_rows = [(int(cluster), rank, names[rank]) for rank, cluster in enumerate(order)]
labels = spark.createDataFrame(label_rows, ["prediction", "profile_rank", "risk_profile"])

profiles = (
    assigned.join(F.broadcast(labels), on="prediction")
    .select(
        "symbol", "quarter_start", "asset_type", "sector", "split",
        *FEATURES, "return_observations", "profile_rank", "risk_profile",
    )
    .cache()
)
profiles.createOrReplaceTempView("risk_profiles")


# --------------------------------------------------
# 6. Spark SQL: what the profiles mean
# --------------------------------------------------

print("\n========== SPARK SQL: PROFILE SUMMARY ==========")
spark.sql("""
    SELECT
        risk_profile,
        COUNT(*) AS symbol_quarters,
        ROUND(AVG(annualized_volatility) * 100, 1) AS avg_volatility_pct,
        ROUND(AVG(max_drawdown) * 100, 1) AS avg_quarter_drawdown_pct,
        ROUND(AVG(beta_vs_benchmark), 2) AS avg_beta,
        ROUND(AVG(avg_intraday_range) * 100, 2) AS avg_intraday_range_pct
    FROM risk_profiles
    GROUP BY risk_profile, profile_rank
    ORDER BY profile_rank
""").show(truncate=False)

print("========== SPARK SQL: PROFILE MIX BY ASSET TYPE ==========")
spark.sql("""
    SELECT
        asset_type,
        risk_profile,
        COUNT(*) AS symbol_quarters,
        ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY asset_type), 1) AS pct_of_asset_type
    FROM risk_profiles
    GROUP BY asset_type, risk_profile, profile_rank
    ORDER BY asset_type, profile_rank
""").show(truncate=False)

print("========== SPARK SQL: SHARE OF QUARTERS EACH SYMBOL SPENT IN EACH PROFILE ==========")
spark.sql(f"""
    SELECT
        symbol,
        COUNT(*) AS quarters,
        ROUND(100.0 * AVG(CASE WHEN profile_rank = 0 THEN 1 ELSE 0 END), 0) AS pct_lowest_profile,
        ROUND(100.0 * AVG(CASE WHEN profile_rank = {best_k - 1} THEN 1 ELSE 0 END), 0) AS pct_highest_profile
    FROM risk_profiles
    GROUP BY symbol
    ORDER BY pct_highest_profile DESC, symbol
""").show(30, truncate=False)

print("========== SAMPLE ASSIGNMENTS: MOST RECENT COMPLETE QUARTER PER SYMBOL (TEST SET) ==========")
spark.sql("""
    SELECT symbol, quarter_start, risk_profile,
           ROUND(annualized_volatility * 100, 1) AS volatility_pct,
           ROUND(max_drawdown * 100, 1) AS quarter_drawdown_pct,
           ROUND(beta_vs_benchmark, 2) AS beta
    FROM (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY quarter_start DESC) AS rn
        FROM risk_profiles
    )
    WHERE rn = 1
    ORDER BY volatility_pct
""").show(30, truncate=False)


# --------------------------------------------------
# 7. Save model and assignments
# --------------------------------------------------

model.write().overwrite().save(MODEL_PATH)
profiles.write.mode("overwrite").parquet(ASSIGNMENT_PATH)

print("Model saved:", MODEL_PATH)
print("Profile assignments saved:", ASSIGNMENT_PATH)
print("\nRisk profile clustering completed successfully.")

spark.stop()
