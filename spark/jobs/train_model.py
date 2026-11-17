import os
from pyspark.sql import SparkSession, Window
from pyspark.sql.functions import (
    col, lead, isnan, count, avg, row_number
)
from pyspark.ml import Pipeline
from pyspark.ml.feature import VectorAssembler, StandardScaler
from pyspark.ml.classification import LogisticRegression
from pyspark.ml.evaluation import (
    MulticlassClassificationEvaluator,
    BinaryClassificationEvaluator
)

# --------------------------------------------------
# 1. Spark session
# --------------------------------------------------

spark = (
    SparkSession.builder
    .appName("FinancialLiteracy-NextDayPrediction")
    .master("local[*]")
    .getOrCreate()
)

spark.sparkContext.setLogLevel("WARN")

BASE = os.getenv("SPARK_OUTPUT", "/opt/spark-app/output")
GOLD_PATH = f"{BASE}/gold/price_features"
MODEL_PATH = f"{BASE}/models/logistic_regression"
PREDICTION_PATH = f"{BASE}/predictions/test_predictions"

# --------------------------------------------------
# 2. Read Gold dataset
# --------------------------------------------------

print("\n========== SPARK ML: LOAD GOLD DATA ==========")

gold = spark.read.parquet(GOLD_PATH)

print(f"Gold input records: {gold.count()}")

# --------------------------------------------------
# 3. Prepare model features
# --------------------------------------------------

# Relative moving-average gaps make price levels
# comparable across different ticker symbols.

data = (
    gold
    .withColumn("sma_5_gap", col("adjusted_close") / col("sma_5") - 1)
    .withColumn("sma_20_gap", col("adjusted_close") / col("sma_20") - 1)
    .withColumn("label", col("next_day_up").cast("double"))
)

feature_cols = [
    "daily_return",
    "return_lag_1",
    "momentum_5d",
    "sma_5_gap",
    "sma_20_gap",
    "volatility_20"
]

# Remove incomplete or invalid feature rows.
for feature in feature_cols:
    data = data.filter(
        col(feature).isNotNull() & ~isnan(col(feature))
    )

data = data.filter(
    col("label").isNotNull()
    & (col("adjusted_close") > 0)
    & (col("sma_5") > 0)
    & (col("sma_20") > 0)
)

print(f"Usable records after feature cleaning: {data.count()}")

# --------------------------------------------------
# 4. Chronological train/test split
# --------------------------------------------------

print("\n========== CHRONOLOGICAL TRAIN/TEST SPLIT ==========")

# Determine the global 80% date boundary.
distinct_dates = (
    data.select("bar_date")
    .distinct()
    .orderBy("bar_date")
    .collect()
)

split_index = int(len(distinct_dates) * 0.80)
test_start_date = distinct_dates[split_index]["bar_date"]

# Find each symbol's next trading date.
history_window = (
    Window.partitionBy("symbol")
    .orderBy("bar_date")
)

data = data.withColumn(
    "next_bar_date",
    lead("bar_date", 1).over(history_window)
)

# Training labels must also be fully before the test period.
train = data.filter(
    (col("bar_date") < test_start_date)
    & (col("next_bar_date") < test_start_date)
)

test = data.filter(
    col("bar_date") >= test_start_date
)

train_count = train.count()
test_count = test.count()

print(f"Test period starts: {test_start_date}")
print(f"Training records: {train_count}")
print(f"Testing records: {test_count}")

if train_count == 0 or test_count == 0:
    raise ValueError("Training or testing dataset is empty.")

print("\nTraining label distribution:")
train.groupBy("label").count().orderBy("label").show()

print("Testing label distribution:")
test.groupBy("label").count().orderBy("label").show()

# --------------------------------------------------
# 5. Build Spark ML pipeline
# --------------------------------------------------

print("\n========== SPARK ML: TRAIN LOGISTIC REGRESSION ==========")

assembler = VectorAssembler(
    inputCols=feature_cols,
    outputCol="raw_features",
    handleInvalid="error"
)

scaler = StandardScaler(
    inputCol="raw_features",
    outputCol="features",
    withMean=True,
    withStd=True
)

classifier = LogisticRegression(
    featuresCol="features",
    labelCol="label",
    maxIter=100,
    regParam=0.01,
    elasticNetParam=0.0
)

pipeline = Pipeline(
    stages=[assembler, scaler, classifier]
)

model = pipeline.fit(train)

print("Logistic Regression training completed.")

# --------------------------------------------------
# 6. Generate test predictions
# --------------------------------------------------

predictions = model.transform(test)

print("\nSample predictions:")
predictions.select(
    "symbol",
    "bar_date",
    "label",
    "prediction",
    "probability"
).orderBy("bar_date").show(20, truncate=False)

# --------------------------------------------------
# 7. Evaluate model
# --------------------------------------------------

print("\n========== MODEL EVALUATION ==========")

accuracy_evaluator = MulticlassClassificationEvaluator(
    labelCol="label",
    predictionCol="prediction",
    metricName="accuracy"
)

f1_evaluator = MulticlassClassificationEvaluator(
    labelCol="label",
    predictionCol="prediction",
    metricName="f1"
)

precision_evaluator = MulticlassClassificationEvaluator(
    labelCol="label",
    predictionCol="prediction",
    metricName="precisionByLabel",
    metricLabel=1.0
)

recall_evaluator = MulticlassClassificationEvaluator(
    labelCol="label",
    predictionCol="prediction",
    metricName="recallByLabel",
    metricLabel=1.0
)

auc_evaluator = BinaryClassificationEvaluator(
    labelCol="label",
    rawPredictionCol="rawPrediction",
    metricName="areaUnderROC"
)

accuracy = accuracy_evaluator.evaluate(predictions)
f1 = f1_evaluator.evaluate(predictions)
precision = precision_evaluator.evaluate(predictions)
recall = recall_evaluator.evaluate(predictions)
auc = auc_evaluator.evaluate(predictions)

print(f"Accuracy:  {accuracy:.4f}")
print(f"Precision: {precision:.4f}")
print(f"Recall:    {recall:.4f}")
print(f"F1 Score:  {f1:.4f}")
print(f"ROC AUC:   {auc:.4f}")

print("\nConfusion matrix:")
(
    predictions
    .groupBy("label", "prediction")
    .count()
    .orderBy("label", "prediction")
    .show()
)

# --------------------------------------------------
# 8. Save model and predictions
# --------------------------------------------------

print("\n========== SAVE MODEL AND PREDICTIONS ==========")

model.write().overwrite().save(MODEL_PATH)

(
    predictions.select(
        "symbol",
        "bar_date",
        "label",
        "prediction",
        "probability"
    )
    .write
    .mode("overwrite")
    .parquet(PREDICTION_PATH)
)

print(f"Model saved: {MODEL_PATH}")
print(f"Test predictions saved: {PREDICTION_PATH}")

print("\nSpark ML pipeline completed successfully.")

spark.stop()
