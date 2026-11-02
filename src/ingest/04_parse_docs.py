# Databricks notebook source
# MAGIC %md
# MAGIC # Day 3: Parse PDFs into page-level text
# MAGIC
# MAGIC Reads every PDF in `/Volumes/{catalog}/raw/docs/` and writes one row per page to
# MAGIC `{catalog}.curated.parsed_docs`. Day 4 chunks this table and builds the vector index.
# MAGIC
# MAGIC I use `pypdf` in layout mode as the main parser: free, fast, and it keeps table rows together.
# MAGIC The last cell tries Databricks `ai_parse_document` on one file so I can compare quality.

# COMMAND ----------

# MAGIC %pip install -q pypdf==5.4.0

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
catalog = dbutils.widgets.get("catalog")
DOCS_DIR = f"/Volumes/{catalog}/raw/docs"
TARGET = f"{catalog}.curated.parsed_docs"

# COMMAND ----------

import os
import re
from datetime import datetime, timezone

from pypdf import PdfReader

MODEL_RE = re.compile(r"(CU-400|EV-220|AC-75|CD-900|BC-48)")
FOOTER_RE = re.compile(r"^\S+\s+Rev\s+\S+\s+\|.*$")   # "NG-MAN-CU400  Rev C  |  CU-400 ... Manual"
PAGE_RE = re.compile(r"^Page \d+$")


def doc_type(filename: str) -> str:
    if filename.startswith("NG_"):
        return "manual"
    if filename.startswith("SOP-"):
        return "sop"
    return "external"  # for example OSHA publications


def clean_page(text: str) -> str:
    """Drop footers, keep table rows on one line with ' | ' between columns."""
    lines, blank = [], False
    for line in text.splitlines():
        s = line.strip()
        if FOOTER_RE.match(s) or PAGE_RE.match(s):
            continue
        if not s:
            if not blank and lines:
                lines.append("")
            blank = True
            continue
        blank = False
        lines.append(re.sub(r"\s{3,}", " | ", s))   # wide gaps are table column breaks
    return "\n".join(lines).strip()


rows = []
parsed_at = datetime.now(timezone.utc)
for fn in sorted(os.listdir(DOCS_DIR)):
    if not fn.lower().endswith(".pdf"):
        continue
    reader = PdfReader(os.path.join(DOCS_DIR, fn))
    title = (reader.metadata.title if reader.metadata and reader.metadata.title else os.path.splitext(fn)[0])
    m = MODEL_RE.search(fn)
    for page_no, page in enumerate(reader.pages, start=1):
        text = clean_page(page.extract_text(extraction_mode="layout") or "")
        rows.append((fn, title, doc_type(fn), m.group(1) if m else None, page_no, len(reader.pages),
                     text, len(text), parsed_at))
    print(f"{fn}: {len(reader.pages)} pages")

schema = ("doc_name string, doc_title string, doc_type string, device_model string, page_number int, "
          "page_count int, text string, char_count int, parsed_at timestamp")
df = spark.createDataFrame(rows, schema)

(df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET))
print(f"Wrote {df.count()} pages to {TARGET}")

# COMMAND ----------

# Quick check: short pages often mean a scanned PDF with no text layer
display(spark.sql(f"""
  SELECT doc_name, doc_type, device_model, count(*) AS pages, min(char_count) AS min_chars, sum(char_count) AS total_chars
  FROM {TARGET} GROUP BY ALL ORDER BY doc_type, doc_name
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Optional: compare with `ai_parse_document`
# MAGIC This calls a Databricks AI function. It may not be enabled on every Free Edition workspace.
# MAGIC If it fails, skip it. pypdf output above is enough for the project.

# COMMAND ----------

try:
    sample = f"{DOCS_DIR}/NG_CU-400_Condensing_Unit_Manual.pdf"
    display(spark.sql(f"""
      SELECT path, ai_parse_document(content) AS parsed
      FROM read_files('{sample}', format => 'binaryFile')
    """))
except Exception as e:
    print(f"ai_parse_document not available here: {str(e)[:300]}")
