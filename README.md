# Ops Assistant: RAG + IoT Agent on Databricks

I am building a chatbot for plant and field operations staff. It answers three kinds of questions:

- **Document questions** from equipment manuals and SOPs, with page citations
- **Data questions** over IoT telemetry in Delta tables
- **Combined questions**, such as "Device D-114 is overheating. What should I check?"

Everything runs on Databricks Free Edition.

## Stack

Unity Catalog, Lakeflow Declarative Pipelines, AI Search (Vector Search), Foundation Model APIs,
Mosaic AI Agent Framework, MLflow 3 (tracing and evaluation), Databricks Apps, Asset Bundles.

## Repo layout

```
databricks.yml        bundle config
resources/            jobs, pipelines, apps (bundle YAML)
src/setup/            Unity Catalog setup
src/ingest/           telemetry and document pipelines
src/rag/              chunking, index, retrieval chain
src/agent/            tool-calling agent
src/eval/             eval datasets and scorers
app/                  chatbot UI (Databricks App)
tests/                unit tests
docs/                 architecture notes, eval results
```

## Setup

```bash
brew tap databricks/tap && brew install databricks
databricks auth login --host <workspace-url>
databricks bundle validate
databricks bundle deploy
databricks bundle run setup_uc
```

## Progress

- [x] Day 1: Workspace, repo, Unity Catalog objects
- [ ] Day 2: Source data
- [ ] Day 3: Bronze, silver, gold pipelines
- [ ] Day 4: Chunking and vector index
- [ ] Day 5: Baseline RAG chain
- [ ] Day 6: Tool-calling agent
- [ ] Day 7: Evaluation
- [ ] Day 8: Register and deploy
- [ ] Day 9: Chatbot UI
- [ ] Day 10: Ops, guardrails, packaging

## Free Edition trade-offs

Serverless compute only, one AI Search endpoint, no GPU serving, up to 3 Apps.
I note each design choice these limits forced in `docs/`.
