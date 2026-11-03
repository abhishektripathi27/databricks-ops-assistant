# Databricks notebook source
# MAGIC %md
# MAGIC # Day 4b: Build the vector index
# MAGIC
# MAGIC Creates (or reuses) the one AI Search / Vector Search endpoint Free Edition allows, then creates a
# MAGIC **Delta Sync index with managed embeddings** on `{catalog}.ai.doc_chunks`. Databricks embeds the
# MAGIC `chunk_text` column with a Foundation Model API embedding endpoint and keeps the index in step
# MAGIC with the table through Change Data Feed. On re-runs it triggers a sync instead of rebuilding.

# COMMAND ----------

# MAGIC %pip install -q databricks-vectorsearch

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("vs_endpoint", "")         # blank = reuse your existing endpoint, or create ops-assistant-vs
dbutils.widgets.text("embedding_endpoint", "")  # blank = pick the first available from PREFERRED_EMBEDDINGS
dbutils.widgets.dropdown("recreate_index", "false", ["false", "true"])

catalog = dbutils.widgets.get("catalog")
SOURCE = f"{catalog}.ai.doc_chunks"
INDEX = f"{catalog}.ai.doc_chunks_index"
RECREATE = dbutils.widgets.get("recreate_index") == "true"
PREFERRED_EMBEDDINGS = ["databricks-gte-large-en", "databricks-qwen3-embedding-0-6b", "databricks-bge-large-en"]

# COMMAND ----------

import time

from databricks.sdk import WorkspaceClient
from databricks.vector_search.client import VectorSearchClient

w = WorkspaceClient()
vsc = VectorSearchClient(disable_notice=True)

# Embedding model: use the widget value, or the first preferred endpoint this workspace has
available = {e.name for e in w.serving_endpoints.list()}
EMBEDDING = dbutils.widgets.get("embedding_endpoint") or next((m for m in PREFERRED_EMBEDDINGS if m in available), None)
if EMBEDDING is None:
    raise RuntimeError(f"No embedding endpoint found. Available endpoints: {sorted(available)}")
print("Embedding endpoint:", EMBEDDING)

# Vector Search endpoint: Free Edition allows one, so reuse whatever exists
existing = [e["name"] for e in vsc.list_endpoints().get("endpoints", [])]
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint") or (existing[0] if existing else "ops-assistant-vs")
if VS_ENDPOINT not in existing:
    print(f"Creating endpoint {VS_ENDPOINT} (5 to 10 minutes)...")
    vsc.create_endpoint(name=VS_ENDPOINT, endpoint_type="STANDARD")
while (state := vsc.get_endpoint(VS_ENDPOINT).get("endpoint_status", {}).get("state")) != "ONLINE":
    print("endpoint state:", state)
    time.sleep(30)
print("Vector Search endpoint:", VS_ENDPOINT, "is ONLINE")

# COMMAND ----------

def index_exists():
    try:
        vsc.get_index(endpoint_name=VS_ENDPOINT, index_name=INDEX).describe()
        return True
    except Exception:
        return False

if RECREATE and index_exists():
    print("Deleting index", INDEX)
    vsc.delete_index(endpoint_name=VS_ENDPOINT, index_name=INDEX)
    while index_exists():
        time.sleep(10)

if index_exists():
    index = vsc.get_index(endpoint_name=VS_ENDPOINT, index_name=INDEX)
    print("Index exists, triggering sync")
    try:
        index.sync()
    except Exception as e:  # a sync already in progress is fine, the wait loop below covers it
        print("sync not started:", str(e)[:200])
else:
    print("Creating index", INDEX)
    index = vsc.create_delta_sync_index(
        endpoint_name=VS_ENDPOINT,
        source_table_name=SOURCE,
        index_name=INDEX,
        pipeline_type="TRIGGERED",
        primary_key="chunk_id",
        embedding_source_column="chunk_text",
        embedding_model_endpoint_name=EMBEDDING,
        columns_to_sync=["chunk_id", "doc_name", "doc_title", "doc_type", "device_model", "section",
                         "page_start", "page_end", "fault_codes", "content", "chunk_text"],
    )

# COMMAND ----------

# Wait until the index is idle and holds every row of the source table.
# Idle states: ONLINE_NO_PENDING_UPDATE (triggered index after a sync) or ONLINE.
# Busy states include ONLINE_TRIGGERED_UPDATE and ONLINE_UPDATING_PIPELINE_RESOURCES.
IDLE_STATES = {"ONLINE_NO_PENDING_UPDATE", "ONLINE"}
expected = spark.table(SOURCE).count()
deadline = time.time() + 30 * 60
while True:
    status = vsc.get_index(endpoint_name=VS_ENDPOINT, index_name=INDEX).describe().get("status", {})
    state, rows = status.get("detailed_state", ""), status.get("indexed_row_count", 0)
    print(f"state={state} indexed_rows={rows}/{expected}")
    if state in IDLE_STATES and rows == expected:
        break
    if "FAILED" in state or time.time() > deadline:
        raise RuntimeError(f"Index not ready: {status}")
    time.sleep(20)
print("Index ready")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Try it

# COMMAND ----------

index = vsc.get_index(endpoint_name=VS_ENDPOINT, index_name=INDEX)
COLS = ["doc_name", "section", "page_start", "fault_codes"]

def show(question, filters=None, query_type="ANN", k=5):
    kwargs = dict(query_text=question, columns=COLS, num_results=k, filters=filters)
    if query_type != "ANN":
        kwargs["query_type"] = query_type
    res = index.similarity_search(**kwargs)
    print(f"\n{question}  [{query_type}{', filters=' + str(filters) if filters else ''}]")
    for row in res.get("result", {}).get("data_array", []):
        print(f"  {row[-1]:.3f}  {row[0][:38]:38}  p{row[2]}  {row[1][:60]}")

show("The walk-in cooler unit is showing high head pressure. What should I check first?")
show("Freezer defrost won't stop. What do I do?")
show("What should I do about E-21?", filters={"device_model": "CU-400"})
show("Who can remove another technician's lock?", filters={"doc_type": ["sop"]})
try:
    show("OL-2 overload trip steps", query_type="HYBRID")
except Exception as e:
    print("Hybrid search not available on this endpoint:", str(e)[:200])
