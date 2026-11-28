"""Show the chunks of one PDF page next to the real page text."""
import json
import sys

import pymupdf

from extract import PDF_PATH, ROOT

CHUNKS_PATH = ROOT / "data" / "processed" / "chunks.jsonl"


def show(pdf_page):
    # 1. the real page, straight from the PDF (no cleaning at all)
    doc = pymupdf.open(PDF_PATH)
    raw = doc[pdf_page - 1].get_text()
    print("=" * 70)
    print(f"REAL PDF TEXT, pdf page {pdf_page}")
    print("=" * 70)
    print(raw)

    # 2. the chunks of this page, from chunks.jsonl
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f]
    mine = [c for c in chunks if c["pdf_page"] == pdf_page]

    print("=" * 70)
    print(f"CHUNKS of pdf page {pdf_page}: {len(mine)} chunk(s)")
    print("=" * 70)
    for c in mine:
        print(f"\n--- {c['chunk_id']} | {c['approx_tokens']} tokens "
              f"| printed page {c['printed_page']} "
              f"| context from {c['context_from_pdf_page']}")
        print("section:", c["section_path"])
        print(c["text"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    show(int(sys.argv[1]))      # the page number comes from the command line