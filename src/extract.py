"""Document engineering for the Dobot CR Series User Guide.

Reads the PDF, keeps both page numbers, removes the header, footer and page
number, cleans bullet symbols, adds the section titles from the PDF
bookmarks, adds quality flags, and saves pages.jsonl.
"""
import json
import re
from pathlib import Path

import pymupdf

# ---------- paths ----------

ROOT = Path(__file__).resolve().parent.parent      # the FactoryMind folder
PDF_PATH = ROOT / "data" / "raw" / "cr_series_user_guide_v1.5_2023-12-27_en.pdf"
OUT_PATH = ROOT / "data" / "processed" / "pages.jsonl"

# ---------- facts about this document ----------

SOURCE = {
    "doc_id": "cr_series_user_guide_v1.5",
    "title": "Dobot CR Series User Guide",
    "issue": "V1.5",
    "date": "2023-12-27",
    "language": "en",
}

PAGE_OFFSET = 8          # number of sheets before printed page 1 (cover + 7 roman pages)
ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii"]  # PDF pages 2 to 8
TOP_LINES = 8            # header, footer and page number are only in the first lines
LOW_TEXT_CHARS = 200     # fewer characters than this = probably an image page
MAX_MISSING_SHARE = 0.05 # allow up to 5% of numbered pages without a found page number

# ---------- patterns ----------

CAPTION_RE = re.compile(r"^Figure \d+\.\d+", re.MULTILINE)   # caption = line STARTS with 'Figure x.y'
BULLET_RE = re.compile(r"[\uf09f\uf06c\u2022]+")    # the two verified bullet glyphs + the normal bullet
PRIVATE_RE = re.compile(r"[\uf09f\uf06c]")          # only the two verified bullet glyphs
ANY_PRIVATE_RE = re.compile(r"[\ue000-\uf8ff]")     # any private-use character (surprise detector)
FIGURE_RE = re.compile(r"\bFigure \d+\.\d+")
TABLE_RE = re.compile(r"\bTable \d+\.\d+")
MATH_RE = re.compile("[\U0001D400-\U0001D7FF]")     # damaged formula chars (math letters)


# ---------- page numbers ----------

def printed_page(pdf_page):
    """Arabic printed page number, or None (cover and roman pages)."""
    if pdf_page <= PAGE_OFFSET:
        return None
    return pdf_page - PAGE_OFFSET


def page_label(pdf_page):
    """The page number as printed on the page: 'i', 'vii', '21', or None."""
    if pdf_page == 1:
        return None
    if pdf_page <= PAGE_OFFSET:
        return ROMAN[pdf_page - 2]
    return str(pdf_page - PAGE_OFFSET)


# ---------- reading ----------

def extract_pages(pdf_path):
    """Return one dict per PDF page with raw text and image count."""
    pages = []
    doc = pymupdf.open(pdf_path)
    for pdf_page, page in enumerate(doc, start=1):
        pages.append({
            "pdf_page": pdf_page,
            "text": page.get_text(),
            "image_count": len(page.get_images()),
        })
    doc.close()
    return pages


def get_sections(pdf_path):
    """Return the PDF bookmarks as a list of (level, title, pdf_page)."""
    doc = pymupdf.open(pdf_path)
    toc = doc.get_toc()
    doc.close()
    return [(level, title.strip(), page) for level, title, page in toc]


def sections_by_page(sections):
    """Map each PDF page to the list of section titles that START on it."""
    by_page = {}
    for level, title, page in sections:
        by_page.setdefault(page, []).append(title)
    return by_page

def section_path_by_page(sections, total_pages):
    """For every PDF page, the breadcrumb of the last section that started on or before it."""
    starts = {}
    for level, title, page in sections:
        starts.setdefault(page, []).append((level, title))
    current = {}                          # level -> title
    result = {}
    for page in range(1, total_pages + 1):
        for level, title in starts.get(page, []):
            current[level] = title
            for deeper in [l for l in current if l > level]:
                del current[deeper]
        result[page] = " > ".join(current[l] for l in sorted(current))
    return result
# ---------- cleaning ----------

def detect_header_lines(pages, min_share=0.5):
    """Lines that repeat in the top lines of at least half of the pages."""
    counts = {}
    for p in pages:
        top = p["text"].splitlines()[:TOP_LINES]
        for line in {x.strip() for x in top if x.strip()}:
            counts[line] = counts.get(line, 0) + 1
    limit = len(pages) * min_share
    return {line for line, n in counts.items() if n >= limit}


def clean_page_text(text, label, header_lines):
    """Clean one page. Return (clean_text, page_number_was_found)."""
    kept = []
    number_found = False
    bullet_pending = False
    for i, line in enumerate(text.splitlines()):
        s = line.strip()
        if i < TOP_LINES and s in header_lines:
            continue
        if i < TOP_LINES and label and not number_found and s == label:
            number_found = True
            continue
        if BULLET_RE.fullmatch(s):       # bullet alone on its line
            bullet_pending = True
            continue
        s = PRIVATE_RE.sub("", s).strip()
        if not s:
            continue
        if bullet_pending:
            s = "- " + s
            bullet_pending = False
        kept.append(s)
    return "\n".join(kept), number_found


# ---------- quality flags ----------

def has_figure_caption(text):
    """True if a line of the page starts with 'Figure x.y'."""
    return CAPTION_RE.search(text) is not None


def quality_flags(text, image_count):
    """Simple facts about the page. The RAG can use them later."""
    empty = len(text) == 0
    low_text = len(text) <= LOW_TEXT_CHARS
    damaged_formula = bool(MATH_RE.search(text))
    return {
        "empty": empty,
        "low_text": low_text,
        "damaged_formula": damaged_formula,
        "mentions_figure": bool(FIGURE_RE.search(text)),
        "mentions_table": bool(TABLE_RE.search(text)),
        "has_figure_caption": has_figure_caption(text),
        "image_count": image_count,
        "needs_visual_check": empty or low_text or damaged_formula,
    }


# ---------- build, check and save ----------

def build_records(pdf_path):
    """Full pipeline: PDF -> list of clean page records."""
    pages = extract_pages(pdf_path)
    header_lines = detect_header_lines(pages)
    sections = get_sections(pdf_path)
    starting = sections_by_page(sections)
    paths = section_path_by_page(sections, len(pages))
    records = []
    for p in pages:
        label = page_label(p["pdf_page"])
        text, number_found = clean_page_text(p["text"], label, header_lines)
        records.append({
            "source": SOURCE,
            "pdf_page": p["pdf_page"],
            "printed_page": printed_page(p["pdf_page"]),
            "page_label": label,
            "sections_starting_here": starting.get(p["pdf_page"], []),
            "section_path": paths[p["pdf_page"]],
            "text": text,
            "char_count": len(text),
            "number_removed": number_found,
            "flags": quality_flags(text, p["image_count"]),
        })
    return records, header_lines


def check_page_numbers(records, max_share=MAX_MISSING_SHARE):
    """Stop the script if the page-number check fails on too many pages."""
    numbered = [r for r in records if r["page_label"]]
    missing = [r["pdf_page"] for r in numbered if not r["number_removed"]]
    share = len(missing) / len(numbered)
    if share > max_share:
        raise ValueError(
            f"Page-number check failed on {len(missing)} of {len(numbered)} pages "
            f"(first: {missing[:5]}). Is PAGE_OFFSET correct?"
        )


def save_records(records, out_path):
    """Save one JSON record per line (JSONL)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def print_report(records, header_lines):
    """Short summary so we can trust the result."""
    def pages_with(flag):
        return [r["pdf_page"] for r in records if r["flags"][flag]]

    missing = [r["pdf_page"] for r in records
               if r["page_label"] and not r["number_removed"]]
    print("Header lines found:", sorted(header_lines))
    print("Pages:", len(records))
    print("Page number NOT found at top:", missing)
    print("Empty pages:", pages_with("empty"))
    print("Low-text pages:", pages_with("low_text"))
    print("Damaged formula pages:", pages_with("damaged_formula"))
    print("Pages that need a visual check:", len(pages_with("needs_visual_check")))
    print("Pages with a figure caption:", len(pages_with("has_figure_caption")))
    left = sum(len(ANY_PRIVATE_RE.findall(r["text"])) for r in records)
    print("Private-use characters left in text:", left)


if __name__ == "__main__":
    records, header_lines = build_records(PDF_PATH)
    check_page_numbers(records)          # stop here if the offset is wrong
    save_records(records, OUT_PATH)
    print_report(records, header_lines)
    print("Saved to", OUT_PATH)