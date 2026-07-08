# `note.note` → tables

Table content lives in `note.note` (not in the `.page` ink tree): the table is
an **inline object of type 22** embedded in the body text's `text_core::Common`
frame, and every cell is a **nested Common frame** of its own — see
[typed-text](./typed-text.md#table-cells-and-inline-objects). The table object
anchors at a U+FFFC char in the body text.

- **Reference parser (render path):** `parse_tables` / `_cell_style` in
  [`pysdocx/note.py`](../../../../pysdocx/note.py) (marker scan).
- **Structural cross-check:** `note_doc_common_frames` in
  [`pysdocx/note_doc.py`](../../../../pysdocx/note_doc.py) — cell frame texts
  equal the scanned cell texts on 2/2 table notes
  ([`spec/tools/analyze_note_doc.py`](../../../../spec/tools/analyze_note_doc.py)).
- **Presence:** there is **no dedicated has-tables flag**. `meta_flags` bit
  `0x2000` — previously promoted as has-tables — actually gates `voice_data`
  ([README](./README.md#field_flags-alias-meta_flags--decoded)); both
  table-bearing corpus notes coincidentally also carry a voice recording.
  Tables are present iff the body frame has an inline object of type 22.
- **Status:** cell text + grid + basic rich text **Decoded**; the table
  object's own block schema (borders, merges, column widths) is **Unknown**.

## Cell record — Decoded

Each cell inside the type-22 table object is:

```
f64 anchor_x, f64 anchor_y     cell bottom-left corner (page coords)
u16 6                          cell tag
<text_core::Common frame>      the cell's own rich-text frame
<fixed structured tail + 32-byte hash-like value, then per-cell fields>
```

The scan's 10-byte "cell marker" `06 00 <u16 kind> 00 00 <u32 char_count>` is
this record seen mid-stream: the `06 00` is the u16 tag, and **`kind` is the
Common frame's `frame_size`** (observed `0x8d`/`0x95`/`0xcd` = 141/149/205 —
the former "does kind encode a style?" unknown is resolved: it doesn't). The
`u16 tag == 6` + plausible-anchor checks hold on 2/2 table notes, 18/18 cells
(`spec/tools/analyze_note_doc.py`).

Cell records are evenly spaced: after each frame comes the same structured
tail family as after a text-box frame (`.. 0f 00 00 00 02 ..` + a 32-byte
hash-like value), a u32 that equals the distance to the next cell record, and
per-cell fields ending in `(f64,f64)` point pairs. The inter-record overhead
is a constant 461 bytes, growing to 486 at each row start (a 25-byte per-row
record). Clustering the anchors reconstructs the row and column grid.

## Cell rich text — Decoded

A cell's styling is the span vector of its own Common frame, with cell-local
coordinates (`start = 0`, `end = char_count`). The render path reads the same
bytes as local TLV runs scoped to the cell and accepts only runs matching the
cell exactly, so a run overrunning into the next cell cannot be
mis-attributed. Bold/italic/underline, color, and font size are read this way;
a plain cell simply carries only the default color+font spans.

## What is Unknown

- The table object's header (before the first cell record) and the semantics
  of the ~461-byte per-cell field block (borders, merges, per-column widths
  as stored fields) and the 25-byte row record.
- The trailing `(3, 2)` u32 pair of the table inline object.

Needs a table-only sample family (plain grid / merged cells / custom borders
+ widths) to vary these one at a time.
