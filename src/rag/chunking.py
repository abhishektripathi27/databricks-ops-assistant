"""Section-aware chunking for the manuals and SOPs.

Strategy
1. Walk each document's pages line by line and split on headings
   ("1. Overview", "E-21: High head pressure", "Preventive Maintenance").
2. Merge tiny sections into the next one so no chunk is just a heading.
3. Pack each section into chunks of about `chunk_tokens`, breaking only between
   lines, with `overlap_tokens` carried into the next chunk.
4. Prefix every chunk with "doc title | section" so the embedding knows where
   the text came from. This is the column the vector index embeds.

Token counts are estimated at 4 characters per token. That is close enough for
English technical text and avoids a tokenizer dependency.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

CHARS_PER_TOKEN = 4

NUMBERED_HEADING = re.compile(r"^\d{1,2}\.\s+[A-Z][^|]{2,70}$")
FAULT_HEADING = re.compile(r"^[A-Z]{1,2}-\d{1,2}:\s+[^|]{3,70}$")
FAULT_CODE = re.compile(r"\b(?:E|F|DF|V|T|P|OL|JM|TH|C)-\d{1,2}\b")
SMALL_WORDS = {"a", "an", "and", "by", "for", "in", "of", "on", "or", "the", "to", "per", "vs"}


def is_heading(line: str) -> bool:
    s = line.strip()
    if not s or "|" in s or s.endswith((".", ":", ",", ";")):
        return False
    if NUMBERED_HEADING.match(s) or FAULT_HEADING.match(s):
        return True
    words = s.split()
    if not 1 <= len(words) <= 7 or any(ch.isdigit() for ch in s):
        return False
    # Title Case: every word that is not a small word starts with a capital letter
    return all(w[0].isupper() for w in words if w.lower() not in SMALL_WORDS) and words[0][0].isupper()


@dataclass
class Section:
    heading: str
    lines: list[tuple[int, str]] = field(default_factory=list)  # (page_number, line)

    @property
    def chars(self) -> int:
        return sum(len(t) + 1 for _, t in self.lines)


@dataclass
class Chunk:
    chunk_id: str
    doc_name: str
    chunk_index: int
    section: str
    page_start: int
    page_end: int
    content: str        # body text only
    chunk_text: str     # "title | section" header + body, embedded by the index
    token_estimate: int
    fault_codes: str    # comma separated codes mentioned in the chunk, for filters


def split_sections(pages: list[tuple[int, str]], doc_title: str) -> list[Section]:
    """pages: list of (page_number, text). Returns sections in order."""
    sections = [Section(heading=doc_title)]
    for page_no, text in pages:
        for line in text.splitlines():
            s = line.strip()
            if s == doc_title:
                continue  # title line repeats the document name
            if is_heading(s):
                sections.append(Section(heading=s))
            elif s or sections[-1].lines:  # skip leading blanks in a section
                sections[-1].lines.append((page_no, s))
    return [sec for sec in sections if any(t for _, t in sec.lines) or sec.heading != doc_title]


def merge_small(sections: list[Section], min_chars: int) -> list[Section]:
    """Fold sections shorter than min_chars into the next section.

    An empty heading (for example "Troubleshooting by Fault Code") becomes a prefix
    of the next heading: "Troubleshooting by Fault Code > E-21: High head pressure".
    A short section with some text keeps its heading and absorbs the next section.
    """
    out: list[Section] = []
    pending: Section | None = None
    for sec in sections:
        if pending is not None:
            if pending.lines:
                page = pending.lines[-1][0]
                sec = Section(pending.heading, pending.lines + [(page, sec.heading)] + sec.lines)
            else:
                sec = Section(f"{pending.heading} > {sec.heading}", sec.lines)
            pending = None
        if sec.chars < min_chars:
            pending = sec
        else:
            out.append(sec)
    if pending is not None:  # a short last section joins the one before it
        if out:
            page = out[-1].lines[-1][0] if out[-1].lines else 1
            out[-1].lines.extend([(page, pending.heading)] + pending.lines)
        else:
            out.append(pending)
    return out


def pack(lines: list[tuple[int, str]], max_chars: int, overlap_chars: int) -> list[list[tuple[int, str]]]:
    """Greedy pack of lines into windows of at most max_chars, with line-level overlap."""
    windows, cur, size = [], [], 0
    for item in lines:
        n = len(item[1]) + 1
        if cur and size + n > max_chars:
            windows.append(cur)
            # carry the tail of the previous window as overlap
            tail, tail_size = [], 0
            for prev in reversed(cur):
                if tail_size + len(prev[1]) + 1 > overlap_chars:
                    break
                tail.insert(0, prev)
                tail_size += len(prev[1]) + 1
            cur, size = list(tail), tail_size
        cur.append(item)
        size += n
    if cur and any(t for _, t in cur):
        windows.append(cur)
    return windows


def chunk_document(doc_name: str, doc_title: str, pages: list[tuple[int, str]],
                   chunk_tokens: int = 400, overlap_tokens: int = 50, min_section_tokens: int = 40) -> list[Chunk]:
    max_chars = chunk_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN
    sections = merge_small(split_sections(pages, doc_title), min_section_tokens * CHARS_PER_TOKEN)

    chunks: list[Chunk] = []
    for sec in sections:
        for window in pack(sec.lines, max_chars, overlap_chars):
            body = "\n".join(t for _, t in window).strip()
            if not body:
                continue
            idx = len(chunks)
            header = f"{doc_title} | {sec.heading}"
            text = f"{header}\n\n{body}"
            chunk_id = hashlib.sha1(f"{doc_name}|{idx}|{body}".encode()).hexdigest()[:16]
            codes = sorted(set(FAULT_CODE.findall(f"{sec.heading}\n{body}")))
            chunks.append(Chunk(
                chunk_id=chunk_id, doc_name=doc_name, chunk_index=idx, section=sec.heading,
                page_start=min(p for p, _ in window), page_end=max(p for p, _ in window),
                content=body, chunk_text=text, token_estimate=len(text) // CHARS_PER_TOKEN,
                fault_codes=",".join(codes)))
    return chunks
