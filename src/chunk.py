"""Chunking: PDF blocks -> chunks.jsonl"""
import json
import re
import sys

import pymupdf

# We reuse these from extract.py, so the numbers live in one place.
from extract import BULLET_RE, PDF_PATH, SOURCE, ROOT

# ---------- paths ----------
PAGES_PATH = ROOT / "data" / "processed" / "pages.jsonl"   # labels per page (input)
OUT_PATH = ROOT / "data" / "processed" / "chunks.jsonl"    # chunks (output)

# ---------- settings ----------
TOP_LIMIT = 70       # a block that starts above this y is the header
BOTTOM_LIMIT = 760   # a block that starts below this y is the footer
MAX_TOKENS = 300     # target size: start a new chunk above this
SOFT_MAX = 400       # a zone this small or smaller stays in ONE chunk


# ---------- Step 1: blocks in reading order, no header/footer ----------
def get_blocks(page):
    kept = []
    # sort=True: blocks come top to bottom, like your eyes read
    for x0, y0, x1, y1, text, number, kind in page.get_text("blocks", sort=True):
        if kind != 0:                               # 0 = text, 1 = image
            continue
        if not text.strip():                        # empty block
            continue
        if y0 < TOP_LIMIT or y0 > BOTTOM_LIMIT:     # header / footer by position
            continue
        kept.append(text)
    return kept


# ---------- Step 2: block -> clean text -> units ----------
def block_to_text(raw):
    items = []              # a paragraph = 1 item, a bullet = 1 item
    start_item = False      # True: the next text starts a new bullet
    for line in raw.splitlines():
        s = line.strip()
        if s and BULLET_RE.fullmatch(s):            # bullet symbol alone on a line
            start_item = True
            continue
        if BULLET_RE.match(s):                      # bullet symbol + text
            s = BULLET_RE.sub("", s, count=1).strip()
            start_item = True
        if not s:
            continue
        if start_item:
            items.append("- " + s)                  # new bullet
            start_item = False
        elif items:
            items[-1] += " " + s                    # wrapped line: glue
        else:
            items.append(s)                         # first line of the block
    return "\n".join(items)


def block_to_units(raw):
    # each paragraph or bullet becomes its own unit
    text = block_to_text(raw)
    return text.split("\n") if text else []


# ---------- Step 3: pack units into chunks ----------
def approx_tokens(text):
    return len(text) // 4                           # rough: 4 characters = 1 token


def is_heading(text):
    # one line, short, does not end like a sentence
    return ("\n" not in text and len(text) < 60
            and not text.endswith((".", ":", ";", ",")))


def pack(units):
    # a small zone stays whole (keeps a warning box together)
    whole = "\n".join(units)
    if approx_tokens(whole) <= SOFT_MAX:
        return [whole] if whole else []
    chunks, current = [], []
    for u in units:
        too_big = approx_tokens("\n".join(current + [u])) > MAX_TOKENS
        # close the chunk only if the last item is NOT a heading
        if current and too_big and not is_heading(current[-1]):
            chunks.append("\n".join(current))
            current = [u]
        else:
            current.append(u)
    if current:
        chunks.append("\n".join(current))
    return chunks


# ---------- Step 4: zones (the section fix) ----------
def clean_title(title):
    # bookmark "1.5 Emergency" -> "Emergency" (headings in the text have no number)
    return re.sub(r"^[\d.]+\s*", "", title).strip()


def split_zones(units, rec, prev_path):
    # text ABOVE the first heading that starts on this page belongs to the
    # previous section. Return a list of (section_label, units).
    titles = {clean_title(t) for t in rec["sections_starting_here"]}
    first = next((i for i, u in enumerate(units) if u in titles), None)
    if first is None or first == 0 or not prev_path:
        return [(rec["section_path"], units)]
    return [(prev_path, units[:first]), (rec["section_path"], units[first:])]


# ---------- Step 5: build chunks for all pages ----------
def build_chunks():
    with open(PAGES_PATH, encoding="utf-8") as f:
        records = [json.loads(line) for line in f]
    doc = pymupdf.open(PDF_PATH)
    chunks = []
    prev_units = []        # units of the last page that had text
    prev_path = ""         # section label of the previous page
    for rec in records:
        page = doc[rec["pdf_page"] - 1]               # Python counts from 0
        units = []
        for b in get_blocks(page):
            units.extend(block_to_units(b))
        own_units = list(units)                       # copy, before adding context
        context_page = None
        # page starts with a lowercase letter: the sentence began on the previous page
        if units and units[0][:1].islower() and prev_units:
            units.insert(0, prev_units[-1])
            context_page = rec["pdf_page"] - 1
        prev_units = own_units or prev_units

        n = 0
        for label, zone_units in split_zones(units, rec, prev_path):
            for text in pack(zone_units):
                n += 1
                chunks.append({
                    "chunk_id": f"{SOURCE['doc_id']}_p{rec['pdf_page']:03d}_{n:02d}",
                    "source": rec["source"],
                    "pdf_page": rec["pdf_page"],              # page of the NEW text
                    "printed_page": rec["printed_page"],      # cite this one
                    "context_from_pdf_page": context_page if n == 1 else None,
                    "section_path": label,                    # label of THIS zone
                    "text": text,
                    "approx_tokens": approx_tokens(text),
                    "needs_visual_check": rec["flags"]["needs_visual_check"],
                    "mentions_figure": rec["flags"]["mentions_figure"],
                    "mentions_table": rec["flags"]["mentions_table"],
                })
        prev_path = rec["section_path"]
    return chunks


# ---------- save and report ----------
def save_chunks(chunks, out_path):
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


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    chunks = build_chunks()
    save_chunks(chunks, OUT_PATH)
    print_report(chunks)