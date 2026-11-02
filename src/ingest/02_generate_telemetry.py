# Databricks notebook source
# MAGIC %md
# MAGIC # Day 2: Generate synthetic IoT telemetry
# MAGIC
# MAGIC Writes three things:
# MAGIC
# MAGIC | Output | Location | Used on |
# MAGIC |---|---|---|
# MAGIC | Device registry (links each device to its manual) | `{catalog}.raw.devices` | Day 3 dim table, Day 6 agent join |
# MAGIC | Raw JSON readings, one folder per day | `/Volumes/{catalog}/raw/telemetry/readings/` | Day 3 Auto Loader bronze |
# MAGIC | Planted incidents (ground truth) | `{catalog}.ai.planted_incidents` | Day 7 evaluation |
# MAGIC
# MAGIC Defaults: 200 devices, 5 sites, 30 days, one reading every 15 minutes (about 576k rows).
# MAGIC The data also contains a little dirt on purpose (sensor errors, null status, duplicates) for Day 3 expectations.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("days", "30")
dbutils.widgets.text("interval_minutes", "15")
dbutils.widgets.text("end_date", "")  # blank = now (UTC). Set YYYY-MM-DD for a fixed, repeatable window.

catalog = dbutils.widgets.get("catalog")
DAYS = int(dbutils.widgets.get("days"))
INTERVAL_MIN = int(dbutils.widgets.get("interval_minutes"))
END_DATE = dbutils.widgets.get("end_date").strip()

# COMMAND ----------

import random
from datetime import date, datetime, timedelta, timezone

from pyspark.sql import functions as F
from pyspark.sql import types as T

try:
    spark.conf.set("spark.sql.session.timeZone", "UTC")
except Exception:
    pass  # some serverless versions lock this; the code below uses epoch seconds either way

LANDING = f"/Volumes/{catalog}/raw/telemetry/readings"
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.raw.telemetry")

# Time window, aligned to the reading interval
if END_DATE:
    end_ts = datetime.fromisoformat(END_DATE).replace(tzinfo=timezone.utc) + timedelta(days=1)
else:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    end_ts = now - timedelta(minutes=now.minute % INTERVAL_MIN)
start_ts = end_ts - timedelta(days=DAYS)
N_TICKS = DAYS * 24 * 60 // INTERVAL_MIN
print(f"Window: {start_ts} to {end_ts} UTC, {N_TICKS} readings per device")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Device registry

# COMMAND ----------

SITES = {
    "JOL": "Joliet, IL", "AUR": "Aurora, CO", "LAK": "Lakeland, FL",
    "STK": "Stockton, CA", "ALN": "Allentown, PA",
}

MODELS = {
    "CU-400": dict(device_type="condensing_unit", zone="Cooler", manual_file="NG_CU-400_Condensing_Unit_Manual.pdf"),
    "EV-220": dict(device_type="freezer_evaporator", zone="Freezer", manual_file="NG_EV-220_Freezer_Evaporator_Manual.pdf"),
    "AC-75":  dict(device_type="air_compressor", zone="Compressor Room", manual_file="NG_AC-75_Air_Compressor_Manual.pdf"),
    "CD-900": dict(device_type="conveyor_drive", zone="Line", manual_file="NG_CD-900_Conveyor_Drive_Manual.pdf"),
    "BC-48":  dict(device_type="battery_charger", zone="Dock Charger", manual_file="NG_BC-48_Battery_Charger_Manual.pdf"),
}

# Normal operating behavior per model. Values match the manuals' normal ranges.
# temp_amp / power_amp = how much the daily load cycle moves the reading.
PARAMS = {
    "CU-400": dict(temp=36.0, temp_sd=0.6, temp_amp=0.8, vib=1.8, vib_sd=0.25, power=4.2, power_sd=0.15, power_amp=0.08, pres=250.0, pres_sd=8.0),
    "EV-220": dict(temp=-10.0, temp_sd=1.0, temp_amp=1.2, vib=1.1, vib_sd=0.15, power=1.85, power_sd=0.1, power_amp=0.06, pres=20.0, pres_sd=1.5),
    "AC-75":  dict(temp=180.0, temp_sd=4.0, temp_amp=6.0, vib=3.0, vib_sd=0.3, power=54.0, power_sd=1.8, power_amp=0.08, pres=125.0, pres_sd=3.0),
    "CD-900": dict(temp=118.0, temp_sd=3.0, temp_amp=6.0, vib=2.4, vib_sd=0.3, power=6.6, power_sd=0.3, power_amp=0.12, pres=None, pres_sd=None),
    "BC-48":  dict(temp=92.0, temp_sd=3.0, temp_amp=5.0, vib=0.2, vib_sd=0.05, power=None, power_sd=None, power_amp=None, pres=None, pres_sd=None),
}

# Devices that carry a planted incident get fixed attributes so the story stays the same every run.
FIXED = {
    "D-114": ("CU-400", "JOL", "Cooler 3"),
    "D-037": ("AC-75", "AUR", "Compressor Room 1"),
    "D-162": ("CD-900", "STK", "Line 2"),
    "D-089": ("EV-220", "LAK", "Freezer 1"),
    "D-200": ("BC-48", "ALN", "Dock Charger 4"),
}

rng = random.Random(42)
model_mix = ["CU-400"] * 5 + ["EV-220"] * 4 + ["CD-900"] * 5 + ["BC-48"] * 4 + ["AC-75"] * 2
site_codes = list(SITES)
devices = []
zone_counter = {}
for i in range(1, 201):
    device_id = f"D-{i:03d}"
    if device_id in FIXED:
        model, site, zone = FIXED[device_id]
    else:
        model = rng.choice(model_mix)
        site = site_codes[(i - 1) % len(site_codes)]
        key = (site, model)
        zone_counter[key] = zone_counter.get(key, 0) + 1
        zone = f"{MODELS[model]['zone']} {zone_counter[key] + 4}"  # +4 keeps clear of fixed zone numbers
    install = date(2018, 1, 1) + timedelta(days=rng.randint(0, 6 * 365))
    devices.append((device_id, model, MODELS[model]["device_type"], "Northgate Equipment Co.",
                    site, SITES[site], zone, install, MODELS[model]["manual_file"]))

devices_schema = T.StructType([
    T.StructField("device_id", T.StringType()), T.StructField("model", T.StringType()),
    T.StructField("device_type", T.StringType()), T.StructField("manufacturer", T.StringType()),
    T.StructField("site_code", T.StringType()), T.StructField("site_name", T.StringType()),
    T.StructField("zone", T.StringType()), T.StructField("install_date", T.DateType()),
    T.StructField("manual_file", T.StringType()),
])
devices_df = spark.createDataFrame(devices, devices_schema)

(devices_df.write.mode("overwrite").option("overwriteSchema", "true")
 .saveAsTable(f"{catalog}.raw.devices"))
display(devices_df.groupBy("site_code", "model").count().orderBy("site_code", "model"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Planted incidents
# MAGIC Times are relative to the end of the window, so "last 3 days" questions stay true whenever you run this.

# COMMAND ----------

def day_start(days_ago):
    d = (end_ts - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)
    return d

INC = {
    # Condenser fouling at Joliet: head pressure and box temp climb over the last 3 days.
    "D-114": dict(start=end_ts - timedelta(days=3), end=end_ts, type="high_head_pressure",
                  faults="E-21, E-42", manual="CU-400 manual: E-21 High head pressure",
                  desc="Head pressure rises from about 250 to 330 psig and box temperature from 36F to about 44F over the last 3 days. Likely dirty condenser coil."),
    # Bearing wear at Aurora: vibration climbs steadily over 10 days.
    "D-037": dict(start=end_ts - timedelta(days=10), end=end_ts, type="bearing_wear",
                  faults="V-02, V-03", manual="AC-75 manual: V-03 Vibration alarm",
                  desc="Airend vibration rises steadily from about 3 to 9 mm/s over 10 days, crossing the 4.5 alert and 7.1 alarm limits."),
    # Afternoon jam at Stockton: overload spike 5 days ago, 14:00 to 16:00 UTC.
    "D-162": dict(start=day_start(5) + timedelta(hours=14), end=day_start(5) + timedelta(hours=16), type="overload_trip",
                  faults="OL-2, TH-4", manual="CD-900 manual: OL-2 Overload trip",
                  desc="Power jumps to about 11 kW and motor temperature to about 152-160F for 2 hours in the afternoon."),
    # Defrost failure at Lakeland: freezer warms overnight 7 days ago, 02:00 to 05:30 UTC.
    "D-089": dict(start=day_start(7) + timedelta(hours=2), end=day_start(7) + timedelta(hours=5, minutes=30), type="defrost_failure",
                  faults="DF-4, F-20", manual="EV-220 manual: DF-4 Defrost termination failure",
                  desc="Box temperature rises from -10F to a peak near 15F over 3.5 hours. Above 10F for more than 60 minutes, so SOP-OPS-002 requires quarantine."),
    # Network outage at Allentown: charger stops reporting 12 to 10 days ago.
    "D-200": dict(start=day_start(12), end=day_start(10), type="comm_loss",
                  faults="C-01", manual="BC-48 manual: C-01 Communication loss",
                  desc="No readings for 48 hours. C-01 logged on the first reading after reconnect."),
}

inc_rows = [(k, v["type"], v["faults"], v["start"], v["end"], v["desc"], v["manual"])
            for k, v in INC.items()]
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.ai")
(spark.createDataFrame(inc_rows, "device_id string, incident_type string, fault_codes string, start_ts timestamp, end_ts timestamp, description string, reference string")
 .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{catalog}.ai.planted_incidents"))
display(spark.table(f"{catalog}.ai.planted_incidents"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Normal readings

# COMMAND ----------

params_df = spark.createDataFrame(
    [(m, p["temp"], p["temp_sd"], p["temp_amp"], p["vib"], p["vib_sd"], p["power"], p["power_sd"], p["power_amp"], p["pres"], p["pres_sd"])
     for m, p in PARAMS.items()],
    "model string, temp double, temp_sd double, temp_amp double, vib double, vib_sd double, "
    "power double, power_sd double, power_amp double, pres double, pres_sd double",
)

start_epoch = int(start_ts.timestamp())
ticks = (spark.range(N_TICKS)
         .withColumn("ts", F.timestamp_seconds(F.lit(start_epoch) + F.col("id") * INTERVAL_MIN * 60))
         .drop("id"))

base = (devices_df.select("device_id", "model").join(params_df, "model").crossJoin(ticks))

# Daily load cycle: peaks mid-afternoon, lowest before dawn (UTC hours treated as site time for simplicity)
hour = F.hour("ts") + F.minute("ts") / 60.0
load = F.sin((hour - 9.0) / 24.0 * 2 * 3.14159265)
charging = (hour >= 22) | (hour < 6) | ((hour >= 12) & (hour < 13.5))

df = (base
      .withColumn("temperature_f", F.col("temp") + F.col("temp_amp") * load + F.col("temp_sd") * F.randn(1))
      .withColumn("vibration_mm_s", F.abs(F.col("vib") * (1 + 0.08 * load) + F.col("vib_sd") * F.randn(2)))
      .withColumn("power_kw",
                  F.when(F.col("model") == "BC-48",
                         F.when(charging, 12.0 + 0.8 * F.randn(3)).otherwise(0.4 + 0.1 * F.randn(3)))
                   .otherwise(F.col("power") * (1 + F.col("power_amp") * load) + F.col("power_sd") * F.randn(3)))
      .withColumn("pressure_psi", F.when(F.col("pres").isNotNull(), F.col("pres") + F.col("pres_sd") * F.randn(4)))
      .withColumn("fault_code", F.lit(None).cast("string")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Apply incidents

# COMMAND ----------

def epoch(x):
    return int(x.timestamp())

def in_window(dev):
    i = INC[dev]
    t = F.unix_timestamp("ts")
    return (F.col("device_id") == dev) & (t >= epoch(i["start"])) & (t < epoch(i["end"]))

def progress(dev):
    """0 at incident start, 1 at incident end."""
    i = INC[dev]
    span = (i["end"] - i["start"]).total_seconds()
    return (F.unix_timestamp("ts") - F.lit(int(i["start"].timestamp()))) / span

# D-114: condenser fouling, gradual
w, r = in_window("D-114"), progress("D-114")
df = (df.withColumn("pressure_psi", F.when(w, F.col("pressure_psi") + 80 * r).otherwise(F.col("pressure_psi")))
        .withColumn("temperature_f", F.when(w, F.col("temperature_f") + 8 * r * r).otherwise(F.col("temperature_f")))
        .withColumn("power_kw", F.when(w, F.col("power_kw") + 0.9 * r).otherwise(F.col("power_kw")))
        .withColumn("fault_code", F.when(w & (F.col("temperature_f") > 41), "E-42")
                                   .when(w & (F.col("pressure_psi") > 300), "E-21")
                                   .otherwise(F.col("fault_code"))))

# D-037: bearing wear, linear vibration rise
w, r = in_window("D-037"), progress("D-037")
df = (df.withColumn("vibration_mm_s", F.when(w, F.col("vibration_mm_s") + 6.0 * r).otherwise(F.col("vibration_mm_s")))
        .withColumn("temperature_f", F.when(w, F.col("temperature_f") + 8.0 * r).otherwise(F.col("temperature_f")))
        .withColumn("fault_code", F.when(w & (F.col("vibration_mm_s") > 7.1), "V-03")
                                   .when(w & (F.col("vibration_mm_s") > 4.5), "V-02")
                                   .otherwise(F.col("fault_code"))))

# D-162: two-hour overload
w = in_window("D-162")
df = (df.withColumn("power_kw", F.when(w, 11.0 + 0.35 * F.randn(5)).otherwise(F.col("power_kw")))
        .withColumn("temperature_f", F.when(w, 152.0 + 4.0 * F.rand(6)).otherwise(F.col("temperature_f")))
        .withColumn("vibration_mm_s", F.when(w, F.col("vibration_mm_s") + 1.5).otherwise(F.col("vibration_mm_s")))
        .withColumn("fault_code", F.when(w & (F.col("temperature_f") > 155), "TH-4")
                                   .when(w, "OL-2")
                                   .otherwise(F.col("fault_code"))))

# D-089: defrost stuck on, temperature arc up to about +15F
w, r = in_window("D-089"), progress("D-089")
df = (df.withColumn("temperature_f", F.when(w, -10.0 + 25.0 * F.sin(r * 3.14159265 * 0.85) + 0.5 * F.randn(7))
                                     .otherwise(F.col("temperature_f")))
        .withColumn("power_kw", F.when(w, 6.5 + 0.1 * F.randn(8)).otherwise(F.col("power_kw")))
        .withColumn("fault_code", F.when(w & (F.col("temperature_f") > 0), "F-20")
                                   .when(w, "DF-4")
                                   .otherwise(F.col("fault_code"))))

# D-200: offline for 48 hours, C-01 logged on reconnect
i = INC["D-200"]
df = (df.filter(~in_window("D-200"))
        .withColumn("fault_code", F.when((F.col("device_id") == "D-200") & (F.unix_timestamp("ts") == epoch(i["end"])), "C-01")
                                   .otherwise(F.col("fault_code"))))

WARN_CODES = ["V-02", "OL-1", "E-14", "F-31", "C-33", "C-01"]
df = df.withColumn("status", F.when(F.col("fault_code").isNull(), "OK")
                              .when(F.col("fault_code").isin(WARN_CODES), "WARN")
                              .otherwise("ALARM"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Add data quality noise and write raw JSON

# COMMAND ----------

out = (df
       .withColumn("temperature_f", F.when(F.rand(10) < 0.002, F.lit(-999.0)).otherwise(F.round("temperature_f", 2)))
       .withColumn("status", F.when(F.rand(11) < 0.001, F.lit(None)).otherwise(F.col("status")))
       .withColumn("vibration_mm_s", F.round("vibration_mm_s", 2))
       .withColumn("power_kw", F.round(F.greatest(F.col("power_kw"), F.lit(0.0)), 2))
       .withColumn("pressure_psi", F.round("pressure_psi", 1))
       .withColumn("event_date", F.to_date("ts"))
       .select("device_id", "ts", "temperature_f", "vibration_mm_s", "power_kw", "pressure_psi",
               "status", "fault_code", "event_date"))

dupes = out.sample(fraction=0.001, seed=12)
out = out.unionByName(dupes)

(out.repartition("event_date")
    .write.mode("overwrite")
    .partitionBy("event_date")
    .option("timestampFormat", "yyyy-MM-dd'T'HH:mm:ss'Z'")
    .json(LANDING))
print(f"Wrote readings to {LANDING}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify

# COMMAND ----------

raw = spark.read.json(LANDING)
print("rows:", raw.count(), "| devices:", raw.select("device_id").distinct().count(),
      "| days:", raw.select("event_date").distinct().count())
display(raw.groupBy("status").count())
display(raw.filter(F.col("fault_code").isNotNull())
           .groupBy("device_id", "fault_code")
           .agg(F.count("*").alias("readings"), F.min("ts").alias("first_seen"), F.max("ts").alias("last_seen"))
           .orderBy("device_id", "first_seen"))
