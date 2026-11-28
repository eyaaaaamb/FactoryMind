"""Chunking: PDF blocks -> chunks (one step at a time)."""
import json
import sys

import pymupdf

# We reuse these from extract.py, so the numbers live in one place.
from extract import BULLET_RE, PDF_PATH, SOURCE, ROOT

# ---------- paths ----------
PAGES_PATH = ROOT / "data" / "processed" / "pages.jsonl"   # labels per page (input)
OUT_PATH = ROOT / "data" / "processed" / "chunks.jsonl"    # chunks (output, later step)

# ---------- settings ----------
TOP_LIMIT = 70       # a block that starts above this y is the header
BOTTOM_LIMIT = 760   # a block that starts below this y is the footer
MAX_TOKENS = 300     # target size of a chunk (a target, not a wall)


# ---------- Step 1: blocks in reading order, without header and footer ----------
def get_blocks(page):
    kept = []
    # sort=True: blocks come from top to bottom, like your eyes read
    for x0, y0, x1, y1, text, number, kind in page.get_text("blocks", sort=True):
        if kind != 0:                      # 0 = text, 1 = image: skip images
            continue
        if not text.strip():               # skip empty blocks
            continue
        if y0 < TOP_LIMIT or y0 > BOTTOM_LIMIT:   # skip header and footer by position
            continue
        kept.append(text)
    return kept


# ---------- Step 2: one block -> clean text ----------
def block_to_text(raw):
    items = []              # finished lines: a paragraph = 1 item, a bullet = 1 item
    start_item = False      # True means: the next text starts a new bullet
    for line in raw.splitlines():
        s = line.strip()
        if s and BULLET_RE.fullmatch(s):     # bullet symbol alone on its line
            start_item = True
            continue
        if BULLET_RE.match(s):               # bullet symbol + text on the same line
            s = BULLET_RE.sub("", s, count=1).strip()
            start_item = True
        if not s:                            # empty line: skip
            continue
        if start_item:
            items.append("- " + s)           # new bullet
            start_item = False
        elif items:
            items[-1] += " " + s             # wrapped line: glue to the last item
        else:
            items.append(s)                  # first line of the block
    return "\n".join(items)

def block_to_units(raw):
    # one block -> a list of units: each paragraph or bullet is its own unit
    text = block_to_text(raw)
    return text.split("\n") if text else []
# ---------- Step 3: pack blocks into chunks ----------
def approx_tokens(text):
    return len(text) // 4                    # rough: 4 characters = 1 token


def is_heading(text):
    # a heading: one line, short, and it does not end like a sentence
    return ("\n" not in text and len(text) < 60
            and not text.endswith((".", ":", ";", ",")))


def pack(units):
    chunks, current = [], []                 # current = the chunk we are building
    for u in units:
        too_big = approx_tokens("\n".join(current + [u])) > MAX_TOKENS
        # close the chunk only if: it is not empty, adding u makes it too big,
        # and its last item is NOT a heading (a heading must stay with its text)
        if current and too_big and not is_heading(current[-1]):
            chunks.append("\n".join(current))
            current = [u]
        else:
            current.append(u)
    if current:
        chunks.append("\n".join(current))     # close the last chunk
    return chunks


# ---------- Steps 4 and 5: build chunks for all pages ----------
def build_chunks():
    # read the labels (page numbers, section, flags) made in Phase 3
    with open(PAGES_PATH, encoding="utf-8") as f:
        records = [json.loads(line) for line in f]
    doc = pymupdf.open(PDF_PATH)
    chunks = []
    prev_units = []                           # blocks of the last page that had text
    for rec in records:
        page = doc[rec["pdf_page"] - 1]       # Python counts from 0
        units = []
        for b in get_blocks(page):
            units.extend(block_to_units(b))   # paragraphs and bullets, one by one
        own_units = list(units)               # copy, before we add context
        context_page = None
        # if the page starts with a lowercase letter, the sentence began
        # on the previous page: put that last block in front
        if units and units[0][:1].islower() and prev_units:
            units.insert(0, prev_units[-1])
            context_page = rec["pdf_page"] - 1
        prev_units = own_units or prev_units
        for n, text in enumerate(pack(units), start=1):
            chunks.append({
                "chunk_id": f"{SOURCE['doc_id']}_p{rec['pdf_page']:03d}_{n:02d}",
                "source": rec["source"],
                "pdf_page": rec["pdf_page"],              # page of the NEW text
                "printed_page": rec["printed_page"],      # use this one for citations
                "context_from_pdf_page": context_page if n == 1 else None,
                "section_path": rec["section_path"],      # one label per page (known limit)
                "text": text,
                "approx_tokens": approx_tokens(text),
                "needs_visual_check": rec["flags"]["needs_visual_check"],
                "mentions_figure": rec["flags"]["mentions_figure"],
                "mentions_table": rec["flags"]["mentions_table"],
            })
    return chunks

def save_chunks(chunks, out_path):
    # one JSON record per line, same style as pages.jsonl
    with open(out_path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def print_report(chunks):
    sizes = sorted(c["approx_tokens"] for c in chunks)
    print("chunks:", len(chunks))
    print("tokens min / median / max:", sizes[0], sizes[len(sizes) // 2], sizes[-1])
    print("chunks over", MAX_TOKENS, "tokens:",
          [c["chunk_id"][-7:] for c in chunks if c["approx_tokens"] > MAX_TOKENS])
    print("chunks under 30 tokens:",
          [c["chunk_id"][-7:] for c in chunks if c["approx_tokens"] < 30])
    print("pages that used the context rule:",
          [c["pdf_page"] for c in chunks if c["context_from_pdf_page"]])
    with_chunk = {c["pdf_page"] for c in chunks}
    print("pages without any chunk:",
          [p for p in range(1, 87) if p not in with_chunk])
    
# ---------- temporary test (we change it at every step) ----------
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    chunks = build_chunks()
    save_chunks(chunks, OUT_PATH)
    for c in chunks:
        if c["pdf_page"] == 26:
            print("---", c["chunk_id"], c["approx_tokens"], "tokens")
            print(c["text"])