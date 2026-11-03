# Day 4: Chunking and retrieval

## Chunking (`src/rag/chunking.py`)

I split on document structure, not fixed windows:

1. Detect headings: numbered sections ("2. Specifications"), fault code headings ("E-21: High head pressure", "OL-2: Overload trip") and short Title Case lines ("Preventive Maintenance").
2. Fold tiny sections into the next one. An empty heading becomes a prefix: "Troubleshooting by Fault Code > E-21: High head pressure".
3. Pack each section into chunks of up to 400 tokens (estimated at 4 characters per token), breaking only between lines, with 50 tokens of overlap.
4. Prefix each chunk with "document title | section" before embedding. A chunk that says "Check that both condenser fans run" then also carries "CU-400 ... E-21".

Result on the corpus: 63 chunks, 71 to 334 tokens. Every fault code gets its own chunk, so a question about E-21 retrieves the E-21 procedure, not half of it.

Metadata kept for filtering: `doc_type` (manual, sop, external), `device_model`, `fault_codes`, `page_start`, `page_end`.

Bug I caught while testing: fault codes with one digit (OL-1, DF-4) were not detected by the first regex, so the CD-900 and EV-220 troubleshooting sections did not split. The unit tests cover these now.

## Index (`src/rag/06_build_index.py`)

- One STANDARD endpoint (the Free Edition limit), reused if it already exists
- Delta Sync index on `ai.doc_chunks`, TRIGGERED, managed embeddings on `chunk_text`
- Embedding model: first available of `databricks-gte-large-en`, `databricks-qwen3-embedding-0-6b`, `databricks-bge-large-en`
- Why Delta Sync with managed embeddings: the table is the source of truth, Change Data Feed keeps the index in step, and I don't run my own embedding job. Direct Vector Access is not available on Free Edition anyway.

## Retrieval metrics (`src/rag/07_retrieval_check.py`)

18 questions in `src/eval/retrieval_questions.json`, each with the chunk(s) that answer it. Phrased the way a technician would ask ("Freezer defrost won't stop"), not with the manual's words.

| Retriever | hit@1 | hit@5 | MRR |
|---|---|---|---|
| TF-IDF keyword baseline (local) | 0.50 | 1.00 | 0.68 |
| Dense (ANN), gte-large, 400 tokens | fill in | fill in | fill in |
| Hybrid, gte-large, 400 tokens | fill in | fill in | fill in |

hit@5 is easy on a 63-chunk corpus. hit@1 and MRR are the numbers that matter: the agent mostly uses the top 3. Adding OSHA PDFs as distractors would make this harder and more realistic.

Results are logged to MLflow (`/Users/<me>/ops_assistant_retrieval`) and appended to `ai.retrieval_eval_runs`.
