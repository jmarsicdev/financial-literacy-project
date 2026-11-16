
from pyspark.sql import SparkSession, Window
from pyspark.sql.functions import col, lead, isnan
from pyspark.ml import Pipeline
from pyspark.ml.feature import VectorAssembler
from pyspark.ml.classification import RandomForestClassifier
from pyspark.ml.evaluation import (
    MulticlassClassificationEvaluator,
    BinaryClassificationEvaluator
)

# --------------------------------------------------
# 1. Spark session
# --------------------------------------------------

spark = (
    SparkSession.builder
    .appName("FinancialLiteracy-RandomForest")
    .master("local[*]")
    .getOrCreate()
)

spark.sparkContext.setLogLevel("WARN")

BASE = "/opt/spark-app/output"

GOLD_PATH = f"{BASE}/gold/price_features"
MODEL_PATH = f"{BASE}/models/random_forest"
PREDICTION_PATH = f"{BASE}/predictions/random_forest_predictions"

# --------------------------------------------------
# 2. Load Gold dataset
# --------------------------------------------------

print("\n========== RANDOM FOREST: LOAD GOLD DATA ==========")

gold = spark.read.parquet(GOLD_PATH)

print(f"Gold input records: {gold.count()}")

# --------------------------------------------------
# 3. Prepare features
# --------------------------------------------------

data = (
    gold
    .withColumn(
        "sma_5_gap",
        col("adjusted_close") / col("sma_5") - 1
    )
    .withColumn(
        "sma_20_gap",
        col("adjusted_close") / col("sma_20") - 1
    )
    .withColumn(
        "label",
        col("next_day_up").cast("double")
    )
)

feature_cols = [
    "daily_return",
    "return_lag_1",
    "momentum_5d",
    "sma_5_gap",
    "sma_20_gap",
    "volatility_20"
]

# Remove incomplete feature records.
for feature in feature_cols:
    data = data.filter(
        col(feature).isNotNull()
        & ~isnan(col(feature))
    )

data = data.filter(
    col("label").isNotNull()
    & (col("adjusted_close") > 0)
    & (col("sma_5") > 0)
    & (col("sma_20") > 0)
)

usable_count = data.count()

print(f"Usable records: {usable_count}")

# --------------------------------------------------
# 4. Chronological train/test split
# --------------------------------------------------

print("\n========== CHRONOLOGICAL TRAIN/TEST SPLIT ==========")

distinct_dates = (
    data.select("bar_date")
    .distinct()
    .orderBy("bar_date")
    .collect()
)

split_index = int(len(distinct_dates) * 0.80)
test_start_date = distinct_dates[split_index]["bar_date"]

history_window = (
    Window.partitionBy("symbol")
    .orderBy("bar_date")
)

data = data.withColumn(
    "next_bar_date",
    lead("bar_date", 1).over(history_window)
)

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
# 5. Build Random Forest pipeline
# --------------------------------------------------

print("\n========== RANDOM FOREST: MODEL TRAINING ==========")

assembler = VectorAssembler(
    inputCols=feature_cols,
    outputCol="features",
    handleInvalid="error"
)

classifier = RandomForestClassifier(
    featuresCol="features",
    labelCol="label",
    numTrees=100,
    maxDepth=8,
    maxBins=32,
    featureSubsetStrategy="sqrt",
    subsamplingRate=0.8,
    seed=42
)

pipeline = Pipeline(
    stages=[assembler, classifier]
)

model = pipeline.fit(train)

print("Random Forest training completed.")

# --------------------------------------------------
# 6. Generate predictions
# --------------------------------------------------

print("\n========== RANDOM FOREST: TEST PREDICTIONS ==========")

predictions = model.transform(test)

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

print("\n========== RANDOM FOREST: EVALUATION ==========")

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

print("\nRandom Forest Results:")
print(f"Accuracy:  {accuracy:.4f}")
print(f"Precision: {precision:.4f}")
print(f"Recall:    {recall:.4f}")
print(f"F1 Score:  {f1:.4f}")
print(f"ROC AUC:   {auc:.4f}")

# --------------------------------------------------
# 8. Confusion matrix
# --------------------------------------------------

print("\n========== CONFUSION MATRIX ==========")

(
    predictions
    .groupBy("label", "prediction")
    .count()
    .orderBy("label", "prediction")
    .show()
)

# --------------------------------------------------
# 9. Feature importance
# --------------------------------------------------

print("\n========== FEATURE IMPORTANCE ==========")

rf_model = model.stages[-1]
importances = rf_model.featureImportances.toArray()

importance_results = sorted(
    zip(feature_cols, importances),
    key=lambda item: item[1],
    reverse=True
)

for feature, importance in importance_results:
    print(f"{feature}: {importance:.6f}")

# --------------------------------------------------
# 10. Save model and predictions
# --------------------------------------------------

print("\n========== SAVE RANDOM FOREST OUTPUTS ==========")

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
print(f"Predictions saved: {PREDICTION_PATH}")

print("\nRandom Forest pipeline completed successfully.")

spark.stop()
