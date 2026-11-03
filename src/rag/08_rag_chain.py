# Databricks notebook source
# MAGIC %md
# MAGIC # Day 5: Baseline RAG chain
# MAGIC
# MAGIC question -> top 3 chunks from the vector index -> LLM answers only from them, with [n] citations.
# MAGIC
# MAGIC - Chain logic: `rag_chain.py` (unit tests in `tests/test_rag_chain.py`)
# MAGIC - System prompt: versioned in the MLflow Prompt Registry as `{catalog}.ai.ops_assistant_system_prompt`, alias `production`
# MAGIC - Tracing: every answer is an MLflow trace with a retriever span (the chunks) and an LLM span (the prompt and response).
# MAGIC   Traces are stored in Unity Catalog tables in `{catalog}.{trace_schema}` by default.
# MAGIC
# MAGIC This chain only knows the documents. Data questions ("which devices alarmed today?") should come back as not found.
# MAGIC The Day 6 agent adds SQL tools for those.

# COMMAND ----------

# MAGIC %pip install -q -U "mlflow[databricks]>=3.11.1" databricks-vectorsearch openai

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("vs_endpoint", "")
dbutils.widgets.text("llm_endpoint", "")      # blank = first available from PREFERRED_LLMS
dbutils.widgets.text("k", "3")
dbutils.widgets.dropdown("trace_destination", "uc", ["uc", "experiment"])
dbutils.widgets.text("trace_schema", "ai")

catalog = dbutils.widgets.get("catalog")
K = int(dbutils.widgets.get("k"))
INDEX = f"{catalog}.ai.doc_chunks_index"
PROMPT_NAME = f"{catalog}.ai.ops_assistant_system_prompt"
TRACE_DEST = dbutils.widgets.get("trace_destination")
TRACE_SCHEMA = dbutils.widgets.get("trace_schema")

# Strong instruction-following chat models first. The notebook prints what your workspace has.
PREFERRED_LLMS = [
    "databricks-claude-sonnet-4-5", "databricks-claude-sonnet-4", "databricks-gpt-oss-120b",
    "databricks-meta-llama-3-3-70b-instruct", "databricks-llama-4-maverick", "databricks-gpt-oss-20b",
]

# COMMAND ----------

import json
import os
import sys

import mlflow
from databricks.sdk import WorkspaceClient
from pyspark.sql import functions as F
from databricks.vector_search.client import VectorSearchClient

sys.path.insert(0, os.path.abspath("."))
import rag_chain as rc

w = WorkspaceClient()
user = spark.sql("SELECT current_user()").first()[0]

chat_endpoints = sorted(e.name for e in w.serving_endpoints.list() if (e.task or "") == "llm/v1/chat")
print("Chat endpoints in this workspace:", chat_endpoints)
LLM = dbutils.widgets.get("llm_endpoint") or next((m for m in PREFERRED_LLMS if m in chat_endpoints), None) \
      or (chat_endpoints[0] if chat_endpoints else None)
if LLM is None:
    raise RuntimeError("No chat endpoint found. Check Serving in the sidebar.")
print("Using LLM:", LLM)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tracing destination
# MAGIC `uc` stores traces as Delta tables in Unity Catalog (needs a SQL warehouse; Free Edition has one).
# MAGIC If your workspace blocks it, re-run with `trace_destination = experiment` to use the experiment's own storage.

# COMMAND ----------

EXPERIMENT = f"/Users/{user}/ops_assistant_rag" + ("_uc" if TRACE_DEST == "uc" else "")

if TRACE_DEST == "uc":
    from mlflow.entities.trace_location import UnityCatalog

    warehouses = list(w.warehouses.list())
    if not warehouses:
        raise RuntimeError("No SQL warehouse found. Re-run with trace_destination = experiment.")
    running = [wh for wh in warehouses if str(wh.state).endswith("RUNNING")]
    wh = (running or warehouses)[0]
    os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = wh.id
    print(f"SQL warehouse for trace tables: {wh.name} ({wh.id})")

    exp = mlflow.get_experiment_by_name(EXPERIMENT)
    location = UnityCatalog(catalog_name=catalog, schema_name=TRACE_SCHEMA)
    if exp is None:
        exp_id = mlflow.create_experiment(name=EXPERIMENT, trace_location=location)
        mlflow.set_experiment(experiment_id=exp_id)
    elif exp.trace_location is None:
        mlflow.set_experiment(experiment_id=exp.experiment_id, trace_location=location)  # bind once
    else:
        if not isinstance(exp.trace_location, UnityCatalog) or exp.trace_location.schema_name != TRACE_SCHEMA:
            raise RuntimeError(f"{EXPERIMENT} is already bound to {exp.trace_location}. Use another experiment name.")
        mlflow.set_experiment(experiment_id=exp.experiment_id)
    exp = mlflow.get_experiment_by_name(EXPERIMENT)
    print("Trace location:", exp.trace_location)
else:
    exp = mlflow.set_experiment(EXPERIMENT)
    print("Traces stored in experiment:", EXPERIMENT)

mlflow.openai.autolog()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Prompt registry
# MAGIC Register a new version only when the prompt text changed, then point the `production` alias at it.

# COMMAND ----------

def sync_prompt(name, template):
    try:
        current = mlflow.genai.load_prompt(f"prompts:/{name}@production")
        if current.template == template:
            print(f"Prompt unchanged: {name} v{current.version}")
            return current
    except Exception:
        pass
    pv = mlflow.genai.register_prompt(name=name, template=template,
                                      commit_message="Baseline RAG system prompt", tags={"day": "5"})
    mlflow.genai.set_prompt_alias(name=name, alias="production", version=pv.version)
    print(f"Registered {name} v{pv.version} as production")
    return pv

try:
    prompt = sync_prompt(PROMPT_NAME, rc.SYSTEM_PROMPT)
    SYSTEM = prompt.template
    PROMPT_VERSION = prompt.version
except Exception as e:
    print("Prompt registry not available, using the prompt from rag_chain.py:", str(e)[:200])
    SYSTEM, PROMPT_VERSION = rc.SYSTEM_PROMPT, "local"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build the chain

# COMMAND ----------

vsc = VectorSearchClient(disable_notice=True)
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint") or vsc.list_endpoints()["endpoints"][0]["name"]
index = vsc.get_index(endpoint_name=VS_ENDPOINT, index_name=INDEX)

client = w.serving_endpoints.get_open_ai_client()
chain = rc.RagChain(retriever=rc.VectorSearchRetriever(index),
                    llm=rc.openai_chat_llm(client, LLM),
                    system_prompt=SYSTEM, k=K)

out = chain.answer("The walk-in cooler unit is showing high head pressure. What should I check first?")
print(out["answer"])
print("\nSources:")
for s in out["sources"]:
    print(f"  [{s['n']}] {s['doc_name']} p{s['page_start']} | {s['section']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run a small question set
# MAGIC Document questions should get cited answers. Data and off-topic questions should come back as not found.

# COMMAND ----------

QUESTIONS = [
    ("doc", "The walk-in cooler unit is showing high head pressure. What should I check first?"),
    ("doc", "Freezer defrost won't stop. What do I do?"),
    ("doc", "Air compressor vibration is above 7 mm/s. How urgent is it and what are the repair steps?"),
    ("doc", "The conveyor motor tripped on overload during the afternoon peak."),
    ("doc", "How long can freezer product stay above 10F before it has to be held?"),
    ("doc", "Who is allowed to remove another technician's lock?"),
    ("doc", "What priority is a V-03 alarm and how fast must someone respond?"),
    ("doc", "How often should condenser coils be cleaned at the Lakeland site?"),
    ("data", "Which devices raised alarms in the last 24 hours?"),
    ("off_topic", "What is the capital of France?"),
]

results = []
for kind, q in QUESTIONS:
    r = chain.answer(q)
    results.append({
        "kind": kind, "question": q, "answer": r["answer"], "not_found": r["not_found"],
        "has_citations": r["has_citations"], "invalid_citations": len(r["invalid_citations"]),
        "sources": "; ".join(f"[{s['n']}] {s['doc_name']} p{s['page_start']}" for s in r["sources"]),
        "latency_s": r["latency_s"],
    })

df = spark.createDataFrame(results)
display(df.select("kind", "question", "answer", "sources", "not_found", "has_citations", "latency_s"))

# COMMAND ----------

# Simple checks. Day 7 replaces these with LLM judges.
doc = [r for r in results if r["kind"] == "doc"]
other = [r for r in results if r["kind"] != "doc"]
summary = {
    "llm": LLM, "k": K, "prompt_version": str(PROMPT_VERSION), "trace_destination": TRACE_DEST,
    "doc_answered_with_citations": f"{sum(r['has_citations'] and not r['not_found'] for r in doc)}/{len(doc)}",
    "non_doc_refused": f"{sum(r['not_found'] for r in other)}/{len(other)}",
    "invalid_citations": sum(r["invalid_citations"] for r in results),
    "avg_latency_s": round(sum(r["latency_s"] for r in results) / len(results), 2),
    "experiment": EXPERIMENT,
}
print(json.dumps(summary, indent=2))

(df.withColumn("llm", F.lit(LLM))
   .withColumn("prompt_version", F.lit(str(PROMPT_VERSION)))
   .withColumn("run_at", F.current_timestamp())
   .write.mode("append").option("mergeSchema", "true").saveAsTable(f"{catalog}.ai.rag_baseline_runs"))

dbutils.notebook.exit(json.dumps(summary))
