# Day 5: Baseline RAG chain

## Flow

question -> vector index (top 3 chunks) -> numbered context -> LLM -> answer with [n] citations -> sources mapped back to doc and page

## Design

- **Answer only from context.** The system prompt says to use only the numbered passages, cite every fact, and reply with a fixed "not found" sentence when the passages don't answer the question. A fixed sentence lets code detect a refusal reliably.
- **Citations are checked in code.** `extract_sources` maps each [n] back to the chunk, and flags numbers that point at no passage (`invalid_citations`). The UI on Day 9 shows these as source cards.
- **Retriever and LLM are injected.** `RagChain` takes two callables. Unit tests use fakes; the notebook passes the Vector Search index and a Databricks-hosted chat model through the OpenAI-compatible client.
- **k = 3.** Retrieval scored hit@5 = 1.00 and MRR = 0.89, so the right chunk is almost always in the top 2. Three passages keep the prompt short and leave less room for distraction.
- **Temperature 0** for repeatable answers.
- **Prompt versioning.** The system prompt lives in the MLflow Prompt Registry as `workspace.ai.ops_assistant_system_prompt`. The notebook registers a new version only when the text changes and moves the `production` alias. Every result row records the prompt version.
- **Tracing.** `@mlflow.trace` on `answer` (CHAIN span) and `retrieve` (RETRIEVER span, returns MLflow `Document`s), plus `mlflow.openai.autolog()` for the LLM call. Traces go to Unity Catalog tables in `workspace.ai`, queryable with SQL.

## First run: citation format bug

The first run reported only 1 of 8 document answers with citations. The answers were all correct.
`databricks-gpt-oss-120b` cites as `【1】` instead of `[1]`, so my parser missed them.
Fix in two places:
- Code: `normalize_citations` rewrites `【1】`, `[1†L3]`, `[1, 3]` and similar to `[1]` before parsing. This holds no matter which model runs.
- Prompt: rule 2 now says to use plain square brackets only. That became prompt version 2 in the registry.

Lesson: check what the model actually returns before trusting a metric built on its output format.

## Results

| Check | Result |
|---|---|
| LLM | fill in |
| Document questions answered with citations | fill in / 8 |
| Data and off-topic questions refused | fill in / 2 |
| Invalid citations | fill in |
| Average latency | fill in s |

The data question ("which devices raised alarms in the last 24 hours?") is supposed to fail here. The documents can't answer it. Day 6 adds SQL tools.
