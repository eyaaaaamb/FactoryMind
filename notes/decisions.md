# FactoryMind: decisions and known limits

Document: Dobot CR Series User Guide V1.5 (2023-12-27), 86 PDF pages.
Written: 2026-11-24. Updated: 2026-11-28.

## Document engineering (Phase 3)

- PAGE_OFFSET = 8. Printed page = PDF page - 8. Checked on all 85 numbered pages. If more than 5% fail, the script stops.
- Header and footer lines are found by repetition: lines that appear in the first 8 lines of at least half of the pages are deleted.
- Only two bullet symbols are deleted (U+F09F and U+F06C). Any other hidden symbol stays, and the report counts it.
- Every page keeps both page numbers (pdf_page and printed_page). Citations use the printed one.
- Every page gets a section_path from the PDF bookmarks, for example "5. Mechanical Specifications > 5.1 CR3 mechanical specifications > 5.1.4 CR3 load curve".
- Pages are never deleted. Empty or low-text pages are flagged, so page numbers always match the PDF.
- Output: data/processed/pages.jsonl (labels and flags per page).

## Chunking (Phase 4)

- Chunk text comes from PDF blocks (sort=True), not from pages.jsonl. pages.jsonl is used only for labels and flags.
- Reason for sort=True: the file order of blocks can differ from the reading order (PDF page 14: the first WARNING box is at the top of the page but comes late in the file).
- Header and footer are removed by y position (blocks starting above 70 or below 760), not by matching text.
- Inside a block, wrapped lines are joined with a space. Bullet symbols become "- ".
- Each paragraph and each bullet is one unit. Units are packed into chunks of about 300 tokens (4 characters = 1 token, a rough estimate).
- MAX_TOKENS = 300 is a target, not a wall. A paragraph is never cut, so 3 chunks are bigger (up to 374 tokens). Accepted.
- A heading is never left alone at the end of a chunk. A table also stays together because its cells look like short headings (checked on Table 4.1, PDF page 26).
- If a page starts with a lowercase letter, the last unit of the previous page is added in front (field context_from_pdf_page).
- Each chunk keeps: chunk_id, pdf_page, printed_page, section_path, context_from_pdf_page, approx_tokens and the flags needs_visual_check, mentions_figure, mentions_table.
- Result: 117 chunks, median about 201 tokens, max 374. Output: data/processed/chunks.jsonl.
- Pages 1 (cover) and 71 (empty) have no chunk. Pages with little text keep a small chunk and stay flagged.

## LLM (Phase 2)

- ollama ps: qwen3.5:4b = 50%/50% CPU/GPU, context 4096, 3.7 GB, about 14 tokens/s.
- Do not raise num_ctx: more context means more memory, more work on the CPU, and a slower model. Keep chunks small.
- Qwen3.5 thinks by default (about 90% of the tokens in my first test). Thinking on or off must be measured in Phase 9.
- The model alone is not grounded: it said the emergency stop "cuts power" and "prevents injury". The manual (printed page 6) says it stops all motions and is not a safeguard.

## Known limits

- Tables stay inside the text. PyMuPDF find_tables damaged numbers (84.89mm became 8489mm), so it is not used.
- Figures are not read. 42 pages have a figure caption. The assistant must say "this page has a figure, please check it" and must not guess.
- 25 pages need a visual check (empty, almost no text, or damaged formulas).
- section_path is one label per page. The first WARNING box on PDF page 14 gets "Emergency recovery", which is probably wrong.
- The context rule (lowercase start) may fire by mistake. PDF page 80 starts with a table cell and is a likely false alarm. Not checked.
- Lines ending with a hyphen are not repaired (heavy- duty).
- The guide covers CR3, CR5, CR7, CR10, CR12, CR16 and the CC162 controller only. It does not cover CR5A, CR10A, CR20A or the CRA series.
- Tests are planned for Phase 10.