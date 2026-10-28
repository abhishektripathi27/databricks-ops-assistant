# Databricks notebook source
# MAGIC %md
# MAGIC # Day 1: Create Unity Catalog objects
# MAGIC Creates the schemas and Volume the project uses. Safe to re-run.
# MAGIC
# MAGIC | Object | Purpose |
# MAGIC |---|---|
# MAGIC | `raw` | Landing zone: raw telemetry, PDFs in the `docs` Volume |
# MAGIC | `curated` | Silver and gold Delta tables |
# MAGIC | `ai` | Chunks, vector index, eval sets, registered agent |

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
catalog = dbutils.widgets.get("catalog")
print(f"Using catalog: {catalog}")

# COMMAND ----------

# Free Edition ships with a 'workspace' catalog. Only try to create a new one
# if you pass a different name.
if catalog != "workspace":
    try:
        spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}")
    except Exception as e:
        raise RuntimeError(
            f"Could not create catalog '{catalog}'. Re-run with catalog=workspace."
        ) from e

for schema in ["raw", "curated", "ai"]:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")

spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.raw.docs")

# COMMAND ----------

# Verify
display(spark.sql(f"SHOW SCHEMAS IN {catalog}"))
display(spark.sql(f"SHOW VOLUMES IN {catalog}.raw"))
print(f"Upload PDFs to: /Volumes/{catalog}/raw/docs/")
