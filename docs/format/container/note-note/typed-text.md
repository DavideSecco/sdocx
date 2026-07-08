# `note.note` → typed rich text

The keyboard-typed text of a note (title + body) and its styling.

- **Structural parser:** `parse_common_frame` / `find_common_frames` /
  `note_doc_common_frames` in
  [`pysdocx/note_doc.py`](../../../../pysdocx/note_doc.py).
- **Render-oriented scans (still the renderer's input):** `parse_typed_text` /
  `_find_text_field` / `_style_runs` / `_paragraph_metadata` in
  [`pysdocx/note.py`](../../../../pysdocx/note.py), cross-checked against the
  structural parse by
  [`spec/tools/analyze_note_doc.py`](../../../../spec/tools/analyze_note_doc.py).
- **Status:** the `text_core::Common` frame layout is **Decoded** (title 14/14,
  body 8/8 text surfaces, span records equal to the TLV scans with zero
  counterexamples); page placement in the renderer is **Heuristic**
  ([`../../heuristics.md`](../../heuristics.md)).

## The `text_core::Common` frame — Decoded

Both the title and body Text blobs (see [README](./README.md)) contain one
rich-text frame with this exact layout (cross-referenced from
`squ1dd13/sdocx2pdf`, validated on the corpus):

```
u32   frame_size          exclusive (bytes after this u32)
u32   char_count          then char_count UTF-16LE code units (the text)
u32   span_count          then span_count span records:
        u16 record_size   >= 16
        u32 span_type     see table below
        u32 start         character index (inclusive)
        u32 end           character index (exclusive)
        u32 interval_type 0 incl-excl, 1 incl-incl, 2 excl-excl, 3 excl-incl
        [record_size-16 bytes payload]
u32   paragraph_count     then paragraph records:
        u16 record_size   >= 12
        u32 paragraph_type
        u32 start         paragraph index (inclusive)
        u32 end           paragraph index (exclusive)
        [record_size-12 bytes payload]
f32×4 margins             left, top, right, bottom (16/10/16/10 body,
                          16.67/0/16.67/0 title on the whole corpus)
u8    gravity             0 top, 1 centre, 2 bottom
u16   section_count       then section_count × (u32, u32) pairs — Unknown
                          ((start,length)-looking; empty-text notes carry
                          ((0xffffffff,1),(0,0)))
-- if format_version >= 2035:
u32   inline_present      boolean written as u32
u32   zero                always 0 on the corpus
      if inline_present: u32 count, then per object:
        u32 frame_size    exclusive
        u32 obj_size      byte size of the embedded object body
        u32 object_type   22 = table, 3 = image on the corpus
        [obj_size bytes]  the object (inner schema not modeled)
        u32 position      index of the U+FFFC anchor char in the frame text
        u32×2             Unknown; observed (3,2) on tables, (0,0) on images
```

The frame is not at a fixed offset inside the blob (the Text/Shape wrapper is
not modeled), so it is located by exhaustive scan; the exact-size constraint
plus the trailing structure make false positives effectively impossible.

## Span records vs the TLV scans

The long-serving `18 00 <tag> 00` TLV scans are these span records seen
byte-for-byte: `18 00` is `record_size = 0x18` (24) and the "tag" is the low
byte of `span_type`. What the scan called `value` is `interval_type`, and its
trailing `enabled` u32 is the first payload u32. Span types and payloads:

| span_type | name | record_size | payload |
|---|---|---|---|
| 1 | foreground_color | 24 | `u32 0xAARRGGBB` + `u32 0` |
| 3 | font_size | 24 | `f32 px` + `u32 0` |
| 5 / 6 / 7 | bold / italic / underline | 24 | `u32 enabled` + `u32 0` |
| 17 | background_color (highlight) | 24 | `u32 0xAARRGGBB` + `u32 0` |
| 20 | strikethrough | 20 | `u32` (usually enabled 0/1; two non-boolean values observed on the benchmark — Unknown) |

Other span types (4 font_name, 9 hypertext, 19 timestamp, 23 formula, …) are
named by `sdocx2pdf` but absent from the corpus.

Structural parsing makes two scan pathologies explainable:

- **Strikethrough "collisions"**: the scan's 4-byte `14 00 14 00` prefix also
  matches paragraph records, so `pysdocx.note` accepts a run only in a clean
  on/off pairing. Structurally there is no ambiguity — spans and paragraphs
  live in separate vectors — and the benchmark's "stray" values are real
  type-20 records with non-boolean payloads.
- **Zero-length spans** (`start == end`) exist in the span vector; the scan
  requires `start < end` and cannot see them.

`analyze_note_doc.py` asserts scan-vs-structural equality per family (color,
font_size, bold, italic, underline, highlight) with those two cases accounted
— zero counterexamples corpus-wide.

## Paragraph records

Same TLV correspondence: `14 00 <tag> 00` is `record_size = 0x14` (20) with an
8-byte payload, and the list marker `1c 00 05 00` is `record_size = 0x1c` (28),
`paragraph_type = 5` (bullet) with a 16-byte payload
`(u32 kind, u32 value, u32 reserved, u32 enabled)` — kind 2 todo / 4 numbered
/ 8 bullet, `value` = number or checked state.

| paragraph_type | name | source |
|---|---|---|
| 2 | indent_level | sdocx2pdf + corpus |
| 3 | align (0 left, 1 right, 2 center) | sdocx2pdf + corpus |
| 4 | line_spacing (f32 in payload) | sdocx2pdf + corpus |
| 5 | bullet (list prefix record) | sdocx2pdf + corpus |
| 6 | parsing_state (≈ one record per character; semantics Unknown) | sdocx2pdf name |
| 8 / 9 | space_before / space_after (f32 payload) | corpus only |
| 10 | style (0 heading1, 1 heading2, 2 heading3, 3 body1) | corpus only |

`start`/`end` index paragraphs (aligned with `text.split("\n")`), not
characters. Types 8/9/10 are **not** in `sdocx2pdf`'s enum — their parser would
reject our styled notes; corpus evidence keeps them.

## Table cells and inline objects

Each table cell is a **nested Common frame** inside the body frame's inline
object of type 22, with cell-local span/paragraph coordinates (this is what
the [tables](./tables.md) scan reads as `TABLE_CELL_PREFIX` records). Inline
images (type 3) anchor at a U+FFFC char in the body text; `position` matches
the anchor index on 3/3 inline objects in the corpus.

## Finding the body text (legacy scan) — Marker

`_find_text_field` locates the body as the longest printable UTF-16LE run
whose preceding `u32` char-count header matches its length (tolerance ±2). It
finds exactly the Common frame text (8/8 text-bearing notes) without knowing
the frame; kept because the renderer consumes its output and it degrades
gracefully on hostile input.

## What is Decoded vs Heuristic

- **Decoded:** the Common frame layout above; all span/paragraph records;
  margins and gravity; inline-object anchoring; table cells as nested frames.
- **Unknown:** `section_data` pair semantics; paragraph type 6 semantics; the
  non-boolean strikethrough payloads; the trailing `(3,2)`/`(0,0)` u32 pair of
  inline objects; the inner schema of the embedded table/image objects.
- **Heuristic (renderer, not format):** how the decoded text is laid out and
  paginated onto pages — `PARA_SPACE_UNIT`, `TYPED_TEXT_BLANK_H`, line height,
  page placement ([`../../heuristics.md`](../../heuristics.md)).
