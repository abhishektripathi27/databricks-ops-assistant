# Databricks notebook source
# MAGIC %md
# MAGIC # Day 4a: Chunk parsed pages
# MAGIC
# MAGIC Reads `{catalog}.curated.parsed_docs` (one row per page) and writes `{catalog}.ai.doc_chunks`
# MAGIC (one row per chunk). The chunking logic lives in `chunking.py` next to this notebook and has
# MAGIC unit tests in `tests/test_chunking.py`.
# MAGIC
# MAGIC Change Data Feed is on, which the Delta Sync vector index needs.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("chunk_tokens", "400")
dbutils.widgets.text("overlap_tokens", "50")

catalog = dbutils.widgets.get("catalog")
CHUNK_TOKENS = int(dbutils.widgets.get("chunk_tokens"))
OVERLAP_TOKENS = int(dbutils.widgets.get("overlap_tokens"))
SOURCE = f"{catalog}.curated.parsed_docs"
TARGET = f"{catalog}.ai.doc_chunks"

# COMMAND ----------

import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.abspath("."))  # notebooks run with their own folder as working directory
from chunking import chunk_document

pages = spark.table(SOURCE).select("doc_name", "doc_title", "doc_type", "device_model", "page_number", "text").collect()

docs = {}
for r in pages:
    key = (r.doc_name, r.doc_title, r.doc_type, r.device_model)
    docs.setdefault(key, []).append((r.page_number, r.text or ""))

rows = []
for (doc_name, doc_title, doc_type, device_model), doc_pages in sorted(docs.items()):
    chunks = chunk_document(doc_name, doc_title, sorted(doc_pages), CHUNK_TOKENS, OVERLAP_TOKENS)
    for c in chunks:
        rows.append({**asdict(c), "doc_title": doc_title, "doc_type": doc_type,
                     "device_model": device_model or "", "chunk_tokens_param": CHUNK_TOKENS})
    print(f"{doc_name}: {len(chunks)} chunks")

# COMMAND ----------

schema = ("chunk_id string, doc_name string, chunk_index int, section string, page_start int, page_end int, "
          "content string, chunk_text string, token_estimate int, fault_codes string, doc_title string, "
          "doc_type string, device_model string, chunk_tokens_param int")
df = spark.createDataFrame([tuple(r[c.split()[0]] for c in schema.split(", ")) for r in rows], schema)

(df.write.mode("overwrite").option("overwriteSchema", "true")
   .option("delta.enableChangeDataFeed", "true")
   .saveAsTable(TARGET))
spark.sql(f"ALTER TABLE {TARGET} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
print(f"Wrote {df.count()} chunks to {TARGET} (chunk_tokens={CHUNK_TOKENS}, overlap_tokens={OVERLAP_TOKENS})")

# COMMAND ----------

display(spark.sql(f"""
  SELECT doc_name, count(*) AS chunks, min(token_estimate) AS min_tokens, max(token_estimate) AS max_tokens
  FROM {TARGET} GROUP BY ALL ORDER BY doc_name
"""))
display(spark.sql(f"SELECT section, fault_codes, chunk_text FROM {TARGET} WHERE doc_name LIKE 'NG_CU-400%' ORDER BY chunk_index"))
