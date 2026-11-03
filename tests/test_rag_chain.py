import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "rag"))
import rag_chain as rc  # noqa: E402

CHUNKS = [
    {"chunk_id": "a1", "doc_name": "NG_CU-400.pdf", "doc_title": "CU-400 Manual", "section": "E-21: High head pressure",
     "page_start": 2, "page_end": 2, "content": "Check that both condenser fans run.", "score": 0.81},
    {"chunk_id": "b2", "doc_name": "SOP-OPS-003.pdf", "doc_title": "Alarm Escalation", "section": "3. Fault Code to Priority Map",
     "page_start": 1, "page_end": 1, "content": "E-21 with box temp above 38F is P1.", "score": 0.74},
]


def fake_retriever(question, k, filters=None):
    return CHUNKS[:k]


def test_context_numbers_and_labels_each_chunk():
    ctx = rc.format_context(CHUNKS)
    assert ctx.startswith("[1] CU-400 Manual | E-21: High head pressure (NG_CU-400.pdf, p2)")
    assert "[2] Alarm Escalation | 3. Fault Code to Priority Map" in ctx


def test_answer_maps_citations_to_sources():
    llm = lambda messages: "1. Check that both condenser fans run [1].\nThis is a P1 event [2][7]."
    out = rc.RagChain(fake_retriever, llm, k=2).answer("E-21 on the cooler?")
    assert [s["doc_name"] for s in out["sources"]] == ["NG_CU-400.pdf", "SOP-OPS-003.pdf"]
    assert out["invalid_citations"] == [7]
    assert out["has_citations"] and not out["not_found"]


def test_not_found_is_detected():
    llm = lambda messages: rc.NOT_FOUND
    out = rc.RagChain(fake_retriever, llm, k=2).answer("What is the capital of France?")
    assert out["not_found"] and not out["has_citations"]


def test_prompt_contains_question_and_rules():
    seen = {}
    def llm(messages):
        seen["m"] = messages
        return "ok [1]"
    rc.RagChain(fake_retriever, llm, k=1).answer("Why is D-114 warm?")
    system, user = seen["m"]
    assert "ONLY the numbered context" in system["content"]
    assert user["content"].endswith("Question: Why is D-114 warm?")
    assert "SOP-OPS-003" not in user["content"]  # k=1 keeps only the first chunk


def test_vector_search_retriever_maps_columns():
    class FakeIndex:
        def similarity_search(self, **kw):
            self.kw = kw
            return {"manifest": {"columns": [{"name": c} for c in rc.CHUNK_COLUMNS] + [{"name": "score"}]},
                    "result": {"data_array": [["a1", "d.pdf", "D", "S", 1, 1, "CU-400", "text", 0.9]]}}
    idx = FakeIndex()
    rows = rc.VectorSearchRetriever(idx)("q", 3, {"device_model": "CU-400"})
    assert rows[0]["chunk_id"] == "a1" and rows[0]["score"] == 0.9
    assert idx.kw["filters"] == {"device_model": "CU-400"} and "query_type" not in idx.kw


def test_citation_styles_are_normalized():
    assert rc.normalize_citations("fans run【1】.") == "fans run[1]."
    assert rc.normalize_citations("P1 [2†L3-L5] and [1, 3]") == "P1 [2] and [1][3]"
    assert rc.normalize_citations("see 【2†source】") == "see [2]"
    assert rc.normalize_citations("no citations here (1)") == "no citations here (1)"


def test_gpt_oss_style_answer_gets_sources():
    llm = lambda messages: "Check that both condenser fans are running【1】. This is P1【2】."
    out = rc.RagChain(fake_retriever, llm, k=2).answer("E-21?")
    assert out["answer"] == "Check that both condenser fans are running[1]. This is P1[2]."
    assert [s["n"] for s in out["sources"]] == [1, 2]


def test_retriever_casts_pages_to_int():
    class FakeIndex:
        def similarity_search(self, **kw):
            return {"manifest": {"columns": [{"name": c} for c in rc.CHUNK_COLUMNS] + [{"name": "score"}]},
                    "result": {"data_array": [["a1", "d.pdf", "D", "S", 2.0, 3.0, "", "text", 0.9]]}}
    row = rc.VectorSearchRetriever(FakeIndex())("q", 1)[0]
    assert row["page_start"] == 2 and isinstance(row["page_start"], int)
