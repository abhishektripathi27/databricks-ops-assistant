"""Score a retriever against questions with known correct chunks.

A search function takes (question, k) and returns a ranked list of dicts with
"doc_name" and "section". A result counts as correct when its doc matches and its
section contains the expected text. Metrics:
  hit@1  share of questions where the top result is correct
  hit@k  share where any of the top k is correct
  mrr    mean reciprocal rank of the first correct result (0 when none)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

SearchFn = Callable[[str, int], list[dict]]


def load_questions(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text())


def is_match(result: dict, expected: list[dict]) -> bool:
    return any(result.get("doc_name") == e["doc"] and e["section"].lower() in (result.get("section") or "").lower()
               for e in expected)


def evaluate(search: SearchFn, questions: list[dict], k: int = 5) -> tuple[dict, list[dict]]:
    rows = []
    for q in questions:
        results = search(q["question"], k)
        rank = next((i + 1 for i, r in enumerate(results[:k]) if is_match(r, q["expected"])), None)
        rows.append({
            "id": q["id"], "question": q["question"], "rank": rank,
            "top_doc": results[0]["doc_name"] if results else None,
            "top_section": results[0]["section"] if results else None,
        })
    n = len(rows)
    metrics = {
        "hit_at_1": sum(1 for r in rows if r["rank"] == 1) / n,
        f"hit_at_{k}": sum(1 for r in rows if r["rank"]) / n,
        "mrr": sum(1 / r["rank"] for r in rows if r["rank"]) / n,
        "questions": n,
    }
    return metrics, rows
