# Databricks notebook source
# MAGIC %md
# MAGIC # Day 4c: Measure retrieval quality
# MAGIC
# MAGIC Runs the questions in `src/eval/retrieval_questions.json` against the index and reports
# MAGIC hit@1, hit@5 and MRR for dense (ANN) and hybrid search. Each run is logged to MLflow and
# MAGIC appended to `{catalog}.ai.retrieval_eval_runs`, so on Day 7 I can compare chunk sizes and
# MAGIC search modes with real numbers.
# MAGIC
# MAGIC Baseline from a local TF-IDF keyword search on the same chunks: hit@1 0.50, hit@5 1.00, MRR 0.68.

# COMMAND ----------

# MAGIC %pip install -q databricks-vectorsearch

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("vs_endpoint", "")
dbutils.widgets.text("k", "5")
catalog = dbutils.widgets.get("catalog")
K = int(dbutils.widgets.get("k"))
INDEX = f"{catalog}.ai.doc_chunks_index"
RESULTS_TABLE = f"{catalog}.ai.retrieval_eval_runs"

# COMMAND ----------

import json
import os
import sys
from datetime import datetime, timezone

import mlflow
from databricks.vector_search.client import VectorSearchClient

sys.path.insert(0, os.path.abspath("../eval"))
from retrieval_eval import evaluate, load_questions

vsc = VectorSearchClient(disable_notice=True)
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint") or vsc.list_endpoints()["endpoints"][0]["name"]
index = vsc.get_index(endpoint_name=VS_ENDPOINT, index_name=INDEX)
desc = index.describe()
embedding = (desc.get("delta_sync_index_spec", {}).get("embedding_source_columns") or [{}])[0].get("embedding_model_endpoint_name")
chunk_tokens = spark.table(f"{catalog}.ai.doc_chunks").selectExpr("max(chunk_tokens_param)").first()[0]
questions = load_questions(os.path.abspath("../eval/retrieval_questions.json"))
print(f"{len(questions)} questions | index {INDEX} | embedding {embedding} | chunk_tokens {chunk_tokens}")


def make_search(query_type):
    def search(question, k):
        kwargs = dict(query_text=question, columns=["doc_name", "section"], num_results=k)
        if query_type != "ANN":
            kwargs["query_type"] = query_type
        data = index.similarity_search(**kwargs).get("result", {}).get("data_array", [])
        return [{"doc_name": r[0], "section": r[1]} for r in data]
    return search

# COMMAND ----------

user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/ops_assistant_retrieval")

runs = []
for query_type in ["ANN", "HYBRID"]:
    try:
        metrics, rows = evaluate(make_search(query_type), questions, k=K)
    except Exception as e:
        print(f"{query_type} skipped: {str(e)[:200]}")
        continue
    params = {"query_type": query_type, "embedding": embedding, "chunk_tokens": chunk_tokens, "k": K}
    with mlflow.start_run(run_name=f"retrieval-{query_type.lower()}-{chunk_tokens}t"):
        mlflow.log_params(params)
        mlflow.log_metrics({k: v for k, v in metrics.items() if k != "questions"})
        mlflow.log_dict(rows, "per_question.json")
    print(query_type, metrics)
    runs.append({**params, **metrics, "per_question": json.dumps(rows),
                 "run_at": datetime.now(timezone.utc)})
    display(spark.createDataFrame(rows))

# COMMAND ----------

if runs:
    df = spark.createDataFrame([
        (r["run_at"], r["query_type"], r["embedding"], int(r["chunk_tokens"]), r["k"], r["hit_at_1"], r[f"hit_at_{K}"],
         r["mrr"], r["questions"], r["per_question"]) for r in runs],
        "run_at timestamp, query_type string, embedding string, chunk_tokens int, k int, hit_at_1 double, "
        "hit_at_k double, mrr double, questions int, per_question string")
    df.write.mode("append").saveAsTable(RESULTS_TABLE)
    display(spark.table(RESULTS_TABLE).drop("per_question").orderBy("run_at"))
