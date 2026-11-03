"""Baseline RAG chain: retrieve top chunks, answer only from them, cite sources.

The retriever and the LLM are passed in as plain callables, so the prompt building
and citation handling can be unit tested without Databricks:

  retriever(question, k, filters) -> list[dict] with chunk fields and "score"
  llm(messages) -> str

On Databricks, `VectorSearchRetriever` and `openai_chat_llm` provide the real ones.
Every step is traced with MLflow, so each answer shows the chunks it used.
"""
from __future__ import annotations

import re
import time
from typing import Callable

import mlflow
from mlflow.entities import Document, SpanType

NOT_FOUND = "I could not find this in the equipment manuals or SOPs."

SYSTEM_PROMPT = f"""You are a maintenance assistant for warehouse equipment at Northgate Distribution.
You answer questions from technicians and shift leads using ONLY the numbered context passages provided.

Rules:
1. Use only facts from the context. Do not add steps, numbers or limits that are not in the context.
2. Cite every fact with the passage number in plain square brackets, for example [1] or [2][3]. Use only this style: no other bracket characters, no line numbers.
3. If the context does not answer the question, reply exactly: "{NOT_FOUND}" and nothing else.
4. For procedures, give numbered steps in the order the document gives them.
5. If a step involves opening equipment or touching moving parts, keep the lockout/tagout instruction from the context.
6. Be brief and direct. No preamble.
"""

# Models cite in different styles: [1], 【1】, [1†L3-L5], 【2†source】, [1, 3]. All become [n].
CITATION_VARIANT = re.compile(r"[\[【]\s*(\d+(?:\s*,\s*\d+)*)\s*(?:[†:][^\]】]*)?[\]】]")
CITATION = re.compile(r"\[(\d+)\]")
RetrieverFn = Callable[[str, int, dict | None], list[dict]]
LlmFn = Callable[[list[dict]], str]


def format_context(chunks: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(chunks, start=1):
        pages = f"p{c['page_start']}" if c.get("page_start") == c.get("page_end") else f"p{c.get('page_start')}-{c.get('page_end')}"
        blocks.append(f"[{i}] {c.get('doc_title', c['doc_name'])} | {c['section']} ({c['doc_name']}, {pages})\n{c['content']}")
    return "\n\n".join(blocks)


def build_messages(system_prompt: str, question: str, chunks: list[dict]) -> list[dict]:
    user = f"Context:\n\n{format_context(chunks)}\n\nQuestion: {question}"
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user}]


def normalize_citations(text: str) -> str:
    """Rewrite every citation style to plain [n], splitting [1, 3] into [1][3]."""
    return CITATION_VARIANT.sub(lambda m: "".join(f"[{n.strip()}]" for n in m.group(1).split(",")), text)


def extract_sources(answer: str, chunks: list[dict]) -> tuple[list[dict], list[int]]:
    """Map [n] markers back to chunks. Returns (cited sources, invalid citation numbers)."""
    cited = sorted({int(n) for n in CITATION.findall(answer)})
    valid = [n for n in cited if 1 <= n <= len(chunks)]
    invalid = [n for n in cited if n not in valid]
    sources = [{"n": n, "doc_name": chunks[n - 1]["doc_name"], "section": chunks[n - 1]["section"],
                "page_start": chunks[n - 1].get("page_start"), "chunk_id": chunks[n - 1].get("chunk_id")}
               for n in valid]
    return sources, invalid


class RagChain:
    def __init__(self, retriever: RetrieverFn, llm: LlmFn, system_prompt: str = SYSTEM_PROMPT, k: int = 3):
        self.retriever = retriever
        self.llm = llm
        self.system_prompt = system_prompt
        self.k = k

    @mlflow.trace(span_type=SpanType.RETRIEVER)
    def retrieve(self, question: str, filters: dict | None = None) -> list[Document]:
        chunks = self.retriever(question, self.k, filters)
        # MLflow Documents let the Day 7 retrieval judges see what was retrieved
        return [Document(page_content=c["content"], id=c.get("chunk_id"),
                         metadata={k: v for k, v in c.items() if k != "content"}) for c in chunks]

    @mlflow.trace(span_type=SpanType.CHAIN)
    def answer(self, question: str, filters: dict | None = None) -> dict:
        start = time.time()
        docs = self.retrieve(question, filters)
        chunks = [{**d.metadata, "content": d.page_content, "chunk_id": d.id} for d in docs]
        text = normalize_citations(self.llm(build_messages(self.system_prompt, question, chunks)).strip())
        sources, invalid = extract_sources(text, chunks)
        not_found = text.startswith(NOT_FOUND[:30])
        return {
            "question": question,
            "answer": text,
            "sources": sources,
            "retrieved": [{"doc_name": c["doc_name"], "section": c["section"], "score": c.get("score")} for c in chunks],
            "not_found": not_found,
            "has_citations": bool(sources),
            "invalid_citations": invalid,
            "latency_s": round(time.time() - start, 2),
        }


# ---------------------------------------------------------------------------
# Databricks implementations
# ---------------------------------------------------------------------------

CHUNK_COLUMNS = ["chunk_id", "doc_name", "doc_title", "section", "page_start", "page_end", "device_model", "content"]


class VectorSearchRetriever:
    def __init__(self, index, query_type: str = "ANN"):
        self.index = index
        self.query_type = query_type

    def __call__(self, question: str, k: int, filters: dict | None = None) -> list[dict]:
        kwargs = dict(query_text=question, columns=CHUNK_COLUMNS, num_results=k)
        if filters:
            kwargs["filters"] = filters
        if self.query_type != "ANN":
            kwargs["query_type"] = self.query_type
        res = self.index.similarity_search(**kwargs)
        cols = [c["name"] for c in res["manifest"]["columns"]]
        rows = [dict(zip(cols, row)) for row in res.get("result", {}).get("data_array", [])]
        for r in rows:  # the index returns numbers as floats (2.0)
            for col in ("page_start", "page_end"):
                if r.get(col) is not None:
                    r[col] = int(r[col])
        return rows


def openai_chat_llm(client, endpoint: str, temperature: float = 0.0, max_tokens: int = 700) -> LlmFn:
    def call(messages: list[dict]) -> str:
        resp = client.chat.completions.create(model=endpoint, messages=messages,
                                              temperature=temperature, max_tokens=max_tokens)
        return resp.choices[0].message.content or ""
    return call
