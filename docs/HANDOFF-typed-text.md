# Handoff — typed-text rendering round (2026-07-03)

Read this before touching `pysdocx/`. It brings you (codex) from your last known point
(`5f421e6`, "transparent corners on rotated images") up to `HEAD`, which is 10 commits ahead on
branch `feat/web-viewer`.

## 0. FIRST: sync your tree, don't re-apply your old changes

Three of the new commits **are your own previously-uncommitted work**, reviewed and committed:

- `058718b` decode paragraph metadata and per-run font sizes  ← yours
- `cdc80d9` decode in-page text-box rich text and rotation    ← yours
- `b2ada92` shared rich-text renderer with wrapping, lists and a text CLI ← yours

So: `git fetch && git reset --hard origin/feat/web-viewer` (or `git pull`). **Do not** replay any
local `note.py` / `page.py` / `render.py` / `__main__.py` edits you may still have — they are
already in history and replaying them will duplicate/conflict. Verify with `git log --oneline -10`.

## 1. What changed since `5f421e6` (chronological)

| commit | what |
|---|---|
| `058718b` | note.py: paragraph metadata (align/indent/line-spacing/heading-body style; numbered/bullet/todo lists via `1c 00 05`) + per-run font sizes |
| `cdc80d9` | page.py: in-page text boxes decode full rich text (bold/italic/underline/strike/color/highlight/font) + rotation angle |
| `b2ada92` | render.py: unified `_render_rich_text` (wrapping, lists, alignment, rotated boxes) + `python -m pysdocx text` diagnostic CLI |
| `8913b46` | note.py: validate the typed-text field by its u32 length header (kills the pen-preload false positive) |
| `3e2c990` | render.py: list markers drawn at the paragraph font size |
| `cc88a29` | note.py: trim typed text to the header-declared length (drop trailing `(` artifact) |
| `72621fa` | render.py: pad list markers; (superseded) page-stretch to fit tall typed text |
| `457cd34` | note.py: decode paragraph space-before (`0x08`) / space-after (`0x09`) |
| `0bff461` | page.py: template id 4 = squared grid, per-id grid pitch |
| `febc3cd` | render.py: apply heading spacing + **paginate** typed text across pages (replaces the page-stretch) |

Only `pysdocx/{note,page,render,__main__}.py` changed. No Rust, no notebooks this round.

## 2. Format knowledge decoded this round (the durable part)

All in `note.note` unless said otherwise.

**Typed-text field** (`note.py:_find_text_field`): the real body text is the longest printable
UTF-16LE run **preceded by a u32 char-count header** (== its length, ±1). This header check is what
distinguishes real text from the pen-preload resource string (`com.samsung…InkPen2`, itself UTF-16LE
but picked up 1 byte off → a long CJK run). Language-independent (works for CJK bodies). Decode
`declared` chars, not the raw run length.

**Character style runs**: `18 00 <tag> 00 | 00 00 | u32 start | u32 end | u32 value | u32 enabled`,
offsets are char indices into the field. Tags: bold 0x05, italic 0x06, underline 0x07, color/
highlight/font families (see `note.py` constants). Strikethrough uses `14 00 14 00`. Font size is a
float in the `enabled` field.

**Paragraph records** (indexed by paragraph number = `text.split("\n")` index, NOT char offset):
`14 00 <tag> 00 | …`. Tags decoded:
- `0x02` indent, `0x03` alignment (0 left/1 right/2 center), `0x04` line-spacing (float in `enabled`),
- `0x08` **space-before**, `0x09` **space-after** (float in `value` — note the different field!),
  present only on styled paragraphs; this is what makes headings breathe,
- `0x0a` style (0 heading1 … 3 body1).
- List/todo prefixes: `1c 00 05 00 00 00 | start | end | kind | value | reserved | enabled`, kind
  4 numbered / 8 bullet / 2 todo (value = number, or 0/1 unchecked/checked).

**In-page text boxes** (`page.py`): text via `06 00 <u16 kind> 00 00 <u32 char_count>`; style runs
right after reuse the same `18 00`/`14 00 14 00` TLV families with box-local offsets. Rotation angle
decoded like images.

**Templates** (`page.py:page_template`): `GRID_TEMPLATE_IDS = {4, 5}` are squared grids. Grid pitch
is **not stored in the .page file** — it's a per-id constant: `GRID_SPACING_BY_ID = {5:102.5, 4:72.5}`
(page units). Origin `(0, 44)`.

## 3. Renderer architecture (render.py)

- `_render_rich_text(ax, parsed, …, sink=None)` is shared by typed text and text boxes.
  - `sink=None` → draws directly (text-box path, unchanged).
  - `sink=<list>` → **records** each segment as `(x, y, seg, style, line_h)` instead of drawing.
    This is the layout pass for pagination.
- Typed-text pagination (document-level flow across the real `.page` files):
  `paginate_typed_text()` runs the sink pass once on a scratch page-sized axes →
  `_paginate_segments()` groups segments into visual lines and splits them by page height (2262):
  **a whole line that would cross the bottom is bumped to the top of the next page** (Samsung
  behaviour; never clipped mid-line) → `draw_typed_page()` draws one slot on a page's axes.
  `render_document` computes the slots on the anchor page (first empty / `typed_text_target`) and
  draws slot `idx - anchor` on each subsequent page. Text boxes still render on their own page and
  coexist with the typed-text continuation.
- `render_typed_text()` (single-axes, no pagination) is kept only for notebook-style callers.

## 4. Heuristics — flagged on purpose (the user wants these visible)

Decoded facts vs calibrated magic numbers:

- **Decoded (trust):** which paragraphs are styled, their space-before/after values, list kinds,
  styles, alignments, font sizes, template id.
- **Calibrated on the squared GT (one file — re-verify if a new sample disagrees):**
  - `PARA_SPACE_UNIT = 4.9` — space-before/after value → page units. Pinned so body1→heading3 = 207
    and heading2→heading1 = 222 page units (both within ~3%).
  - `TYPED_TEXT_BLANK_H = 75` — empty-paragraph height. **Least certain**: implies a blank line is
    taller than a text line; it's what lands the GT anchors (Testo top≈74, heading3 top≈1944) and
    makes heading2 fall to page 2.
  - `GRID_SPACING_BY_ID` pitches (72.5 / 102.5) — measured from GT photos, not in the file.
  - `TYPED_TEXT_PAGE_PAD = 40`.
  - Pre-existing: `*1.36` (font pt scale), `/1.35` (line-spacing normalization), `line_h=66`,
    `indent*70`.

## 5. ROTATED TEXT-BOX STATUS

On `samples/OnlyTextTypeWritten_squared_260703_013624.sdocx`, page 2, the rotated text boxes now use
decoded `frame_midpoints` when available. The **90° text box** keeps the GT-like three logical rows:
`testo dentro una casella di`, `testo in grassetto e in`, `corsivo ruotato di 90 gradi`.

The remaining caveat is still important: inner text-box layout is renderer-calibrated, not fully
decoded. Non-vertical rotated boxes currently shrink the projected wrap width by a small heuristic
inset so the 16° sample wraps `2 righe inclinata` onto the third line.

## 6. How to verify (always use the venv — matplotlib etc. are only there)

```
.venv/bin/python -m pysdocx text  samples/<file>.sdocx            # decoded metadata (add --json)
.venv/bin/python -m pysdocx render samples/<file>.sdocx <outdir>  # one PNG per page
```

Ground-truth photos live next to each sample in `samples/<stem>_gt/` or `samples/<stem>/`.
Key check file: `OnlyTextTypeWritten_squared_260703_013624` — its 2 GT photos have the squared grid,
so you can measure spacing in grid cells. Correct pagination = p1 ends at "questo è heading 3",
p2 starts at "questo è heading 2" and holds the 3 text boxes, p3 blank.

## 7. Working norms (from the user)

- Iterate in **pysdocx first**; port to Rust only at checkpoints, not every round.
- **Never `git commit` without explicit approval.** Propose, show the diff, wait.
- **Flag every heuristic / magic number explicitly** — decoded facts and calibrated guesses must be
  distinguishable.
- Prefer grounded RE driven by single-variable ground-truth samples the user creates.
