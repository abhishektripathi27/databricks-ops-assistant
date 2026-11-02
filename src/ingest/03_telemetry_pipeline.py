"""Day 3: Telemetry pipeline (Lakeflow Spark Declarative Pipelines).

bronze_readings             streaming table   raw JSON from the Volume via Auto Loader
silver_readings             streaming table   typed, status repaired, deduped, bad rows dropped
silver_readings_quarantine  streaming table   rows that failed a silver rule, with the rule names
dim_device                  materialized view device registry (model, site, manual file)
gold_device_hourly          materialized view hourly stats per device
gold_fault_events           materialized view one row per fault episode
gold_device_status          materialized view latest reading per device

Pipeline configuration keys (set in resources/telemetry_pipeline.yml):
  landing_path    /Volumes/<catalog>/raw/telemetry/readings
  source_catalog  catalog that holds raw.devices
"""
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

try:
    from pyspark import pipelines as dp
except ImportError:
    try:  # older Databricks runtimes
        import dlt as dp
        dp.materialized_view = dp.table
    except ImportError:  # plain Spark (unit tests): only the helper functions are used
        dp = None

# ---------------------------------------------------------------------------
# Shared logic (plain functions so they can be unit tested without a pipeline)
# ---------------------------------------------------------------------------

RAW_SCHEMA = T.StructType([
    T.StructField("device_id", T.StringType()),
    T.StructField("ts", T.StringType()),
    T.StructField("temperature_f", T.DoubleType()),
    T.StructField("vibration_mm_s", T.DoubleType()),
    T.StructField("power_kw", T.DoubleType()),
    T.StructField("pressure_psi", T.DoubleType()),
    T.StructField("status", T.StringType()),
    T.StructField("fault_code", T.StringType()),
])

WARN_CODES = ["V-02", "OL-1", "E-14", "F-31", "C-33", "C-01"]

# Silver rules. A row must pass all of them to reach silver_readings.
SILVER_RULES = {
    "has_device_id": "device_id IS NOT NULL",
    "has_timestamp": "ts IS NOT NULL",
    "temperature_in_range": "temperature_f BETWEEN -60 AND 300",  # catches the -999 sensor error value
}

# A fault episode ends when a device goes this long without a faulted reading.
# Readings near a limit flap on and off, so the gap is wide enough to merge those flaps.
EPISODE_GAP_MINUTES = 180
# Episodes with fewer faulted readings than this are flagged as transient blips.
MIN_SUSTAINED_READINGS = 3


def clean_readings(df: DataFrame) -> DataFrame:
    """Type the timestamp and rebuild a missing status from the fault code."""
    derived_status = (F.when(F.col("fault_code").isNull(), "OK")
                       .when(F.col("fault_code").isin(WARN_CODES), "WARN")
                       .otherwise("ALARM"))
    return (df
            .withColumn("ts", F.to_timestamp("ts"))
            .withColumn("status_was_null", F.col("status").isNull())
            .withColumn("status", F.coalesce(F.col("status"), derived_status))
            .withColumn("event_date", F.to_date("ts")))


def failed_rules(df: DataFrame) -> DataFrame:
    """Keep rows that fail any silver rule and list which rules failed."""
    checks = [F.when(~F.coalesce(F.expr(rule), F.lit(False)), F.lit(name)) for name, rule in SILVER_RULES.items()]
    return (df.withColumn("failed_rules", F.filter(F.array(*checks), lambda x: x.isNotNull()))
              .filter(F.size("failed_rules") > 0))


def hourly_stats(readings: DataFrame) -> DataFrame:
    return (readings
            .groupBy("device_id", F.date_trunc("hour", "ts").alias("hour"))
            .agg(F.count("*").alias("readings"),
                 F.round(F.avg("temperature_f"), 2).alias("avg_temperature_f"),
                 F.max("temperature_f").alias("max_temperature_f"),
                 F.min("temperature_f").alias("min_temperature_f"),
                 F.round(F.avg("vibration_mm_s"), 2).alias("avg_vibration_mm_s"),
                 F.max("vibration_mm_s").alias("max_vibration_mm_s"),
                 F.round(F.avg("power_kw"), 2).alias("avg_power_kw"),
                 F.max("power_kw").alias("max_power_kw"),
                 F.round(F.avg("pressure_psi"), 1).alias("avg_pressure_psi"),
                 F.max("pressure_psi").alias("max_pressure_psi"),
                 F.sum(F.when(F.col("status") == "ALARM", 1).otherwise(0)).alias("alarm_readings"),
                 F.sum(F.when(F.col("status") == "WARN", 1).otherwise(0)).alias("warn_readings")))


def fault_episodes(readings: DataFrame) -> DataFrame:
    """Collapse faulted readings into episodes (gaps and islands).

    A device can flip between related codes (V-02 and V-03, E-21 and E-42) as values
    hover near a limit. One episode keeps all codes seen, the latest code and the peaks.
    """
    w = Window.partitionBy("device_id").orderBy("ts")
    faulted = (readings.filter(F.col("fault_code").isNotNull())
               .withColumn("prev_ts", F.lag("ts").over(w))
               .withColumn("new_episode",
                           (F.col("prev_ts").isNull() |
                            ((F.unix_timestamp("ts") - F.unix_timestamp("prev_ts")) > EPISODE_GAP_MINUTES * 60)).cast("int"))
               .withColumn("episode_seq", F.sum("new_episode").over(w)))
    return (faulted
            .groupBy("device_id", "episode_seq")
            .agg(F.min("ts").alias("first_seen"),
                 F.max("ts").alias("last_seen"),
                 F.count("*").alias("faulted_readings"),
                 F.array_sort(F.collect_set("fault_code")).alias("fault_codes"),
                 F.max_by("fault_code", "ts").alias("latest_fault_code"),
                 F.max(F.when(F.col("status") == "ALARM", 1).otherwise(0)).cast("boolean").alias("reached_alarm"),
                 F.max("temperature_f").alias("peak_temperature_f"),
                 F.max("vibration_mm_s").alias("peak_vibration_mm_s"),
                 F.max("power_kw").alias("peak_power_kw"),
                 F.max("pressure_psi").alias("peak_pressure_psi"))
            .withColumn("duration_minutes",
                        ((F.unix_timestamp("last_seen") - F.unix_timestamp("first_seen")) / 60).cast("int"))
            # C-01 is logged once on reconnect by design, so it is never a blip
            .withColumn("is_transient", (F.col("faulted_readings") < MIN_SUSTAINED_READINGS)
                                        & ~F.array_contains("fault_codes", "C-01"))
            .withColumn("episode_id", F.concat_ws("-", "device_id", F.date_format("first_seen", "yyyyMMddHHmm")))
            .drop("episode_seq"))


def latest_status(readings: DataFrame) -> DataFrame:
    as_of = readings.agg(F.max("ts").alias("as_of"))
    latest = (readings.groupBy("device_id")
              .agg(F.max("ts").alias("last_seen"),
                   F.max_by(F.struct("temperature_f", "vibration_mm_s", "power_kw", "pressure_psi",
                                     "status", "fault_code"), "ts").alias("r")))
    recent = (readings.crossJoin(as_of)
              .filter(F.col("ts") > F.col("as_of") - F.expr("INTERVAL 24 HOURS"))
              .groupBy("device_id")
              .agg(F.sum(F.when(F.col("status") == "ALARM", 1).otherwise(0)).alias("alarm_readings_24h"),
                   F.sum(F.when(F.col("status") == "WARN", 1).otherwise(0)).alias("warn_readings_24h")))
    return (latest.crossJoin(as_of).join(recent, "device_id", "left")
            .select("device_id", "as_of", "last_seen",
                    ((F.unix_timestamp("as_of") - F.unix_timestamp("last_seen")) / 60).cast("int").alias("minutes_since_last_reading"),
                    "r.*",
                    F.coalesce("alarm_readings_24h", F.lit(0)).alias("alarm_readings_24h"),
                    F.coalesce("warn_readings_24h", F.lit(0)).alias("warn_readings_24h")))


# ---------------------------------------------------------------------------
# Pipeline datasets (only defined when running inside a pipeline)
# ---------------------------------------------------------------------------

def _define_pipeline():
    landing = spark.conf.get("landing_path")  # noqa: F821 (spark is provided by the pipeline)
    source_catalog = spark.conf.get("source_catalog", "workspace")  # noqa: F821
    device_cols = ["device_id", "model", "device_type", "site_code", "site_name", "zone", "manual_file"]

    @dp.table(name="bronze_readings", comment="Raw telemetry from JSON files, as received.",
              table_properties={"quality": "bronze"})
    @dp.expect("status_present", "status IS NOT NULL")                   # warn only: tracked, not dropped
    @dp.expect("temperature_not_sentinel", "temperature_f <> -999")      # warn only
    def bronze_readings():
        return (spark.readStream.format("cloudFiles")  # noqa: F821
                .option("cloudFiles.format", "json")
                .schema(RAW_SCHEMA)
                .load(landing)
                .select("*",
                        F.col("_metadata.file_path").alias("source_file"),
                        F.current_timestamp().alias("ingested_at")))

    @dp.table(name="silver_readings", comment="Typed, deduplicated readings that passed all quality rules.",
              table_properties={"quality": "silver"}, cluster_by=["device_id", "event_date"])
    @dp.expect_all_or_drop(SILVER_RULES)
    def silver_readings():
        return (clean_readings(spark.readStream.table("bronze_readings"))  # noqa: F821
                .withWatermark("ts", "2 hours")
                .dropDuplicatesWithinWatermark(["device_id", "ts"])
                .drop("source_file"))

    @dp.table(name="silver_readings_quarantine", comment="Readings that failed a silver rule.",
              table_properties={"quality": "quarantine"})
    def silver_readings_quarantine():
        return failed_rules(clean_readings(spark.readStream.table("bronze_readings")))  # noqa: F821

    @dp.materialized_view(name="dim_device", comment="Device registry: model, site, zone and manual file.")
    def dim_device():
        return spark.read.table(f"{source_catalog}.raw.devices")  # noqa: F821

    @dp.materialized_view(name="gold_device_hourly", comment="Hourly sensor stats per device.",
                          table_properties={"quality": "gold"})
    def gold_device_hourly():
        hourly = hourly_stats(spark.read.table("silver_readings"))  # noqa: F821
        return hourly.join(spark.read.table("dim_device").select("device_id", "model", "site_code"), "device_id", "left")  # noqa: F821

    @dp.materialized_view(name="gold_fault_events", comment="One row per fault episode, with codes and peak values.",
                          table_properties={"quality": "gold"})
    def gold_fault_events():
        episodes = fault_episodes(spark.read.table("silver_readings"))  # noqa: F821
        return episodes.join(spark.read.table("dim_device").select(*device_cols), "device_id", "left")  # noqa: F821

    @dp.materialized_view(name="gold_device_status", comment="Latest reading per device and alarm counts for the last 24 hours of data.",
                          table_properties={"quality": "gold"})
    def gold_device_status():
        status = latest_status(spark.read.table("silver_readings"))  # noqa: F821
        return status.join(spark.read.table("dim_device").select(*device_cols), "device_id", "left")  # noqa: F821


try:
    spark  # noqa: B018, F821
    _IN_PIPELINE = spark.conf.get("landing_path", None) is not None  # noqa: F821
except NameError:
    _IN_PIPELINE = False

if _IN_PIPELINE:
    _define_pipeline()
