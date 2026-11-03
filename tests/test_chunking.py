import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "rag"))
from chunking import chunk_document, is_heading  # noqa: E402


def test_heading_detection():
    assert is_heading("1. Overview")
    assert is_heading("E-21: High head pressure")
    assert is_heading("OL-2: Overload trip")
    assert is_heading("Troubleshooting by Fault Code")
    assert not is_heading("Corrective actions:")
    assert not is_heading("Code | Name | Trigger condition | Severity")
    assert not is_heading("Failed condenser fan motor or seized fan blade.")
    assert not is_heading("Head pressure above 300 psig for 10 consecutive")


PAGES = [
    (1, "Test Manual\n1. Overview\n" + "The unit cools things. " * 20 + "\nFault Code Reference\n"),
    (2, "E-21: High head pressure\nTrigger: pressure above 300 psig.\n" + "Clean the coil and check the fans. " * 10
        + "\nE-14: Low suction pressure\n" + "Check for ice on the evaporator. " * 10),
]


def test_one_chunk_per_fault_and_empty_heading_prefix():
    chunks = chunk_document("t.pdf", "Test Manual", PAGES, chunk_tokens=400, overlap_tokens=0)
    sections = [c.section for c in chunks]
    assert "Fault Code Reference > E-21: High head pressure" in sections
    assert "E-14: Low suction pressure" in sections
    e21 = next(c for c in chunks if c.section.endswith("E-21: High head pressure"))
    assert e21.fault_codes == "E-21"
    assert e21.page_start == 2
    assert e21.chunk_text.startswith("Test Manual | Fault Code Reference > E-21")


def test_long_section_splits_with_overlap():
    pages = [(1, "Doc\n1. Long\n" + "\n".join(f"Line {i} has some words in it." for i in range(200)))]
    chunks = chunk_document("d.pdf", "Doc", pages, chunk_tokens=100, overlap_tokens=20)
    assert len(chunks) > 5
    assert all(c.token_estimate <= 115 for c in chunks)  # 100 + header
    first_tail = chunks[0].content.splitlines()[-1]
    assert first_tail in chunks[1].content  # overlap carried forward


def test_chunk_ids_are_stable():
    a = chunk_document("t.pdf", "Test Manual", PAGES)
    b = chunk_document("t.pdf", "Test Manual", PAGES)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
