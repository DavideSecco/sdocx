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

## Cell marker — Decoded (scan view)

Each cell is preceded by a 10-byte marker, immediately followed by the cell's
UTF-16LE text:

```
06 00 <u16 kind> 00 00 <u32 char_count>   marker (10 bytes)
<char_count * 2 bytes UTF-16LE>           cell text
```

Structurally, `<u32 char_count><text>` is the head of the cell's own Common
frame; the `06 00 <kind>` bytes belong to the surrounding (not yet modeled)
cell record of the table object. Observed `kind` values: `0x8d`, `0x95`,
`0xcd`. The cell's bottom-left corner in page coordinates is the `f64` pair
located **before** the marker: x at `marker - 16`, y at `marker - 8`.
Clustering these anchors reconstructs the row and column grid.

## Cell rich text — Decoded

A cell's styling is the span vector of its own Common frame, with cell-local
coordinates (`start = 0`, `end = char_count`). The render path reads the same
bytes as local TLV runs scoped to the cell and accepts only runs matching the
cell exactly, so a run overrunning into the next cell cannot be
mis-attributed. Bold/italic/underline, color, and font size are read this way;
a plain cell simply carries only the default color+font spans.

## What is Unknown

- The table object's block-level schema inside the inline object (borders,
  merged cells, per-column widths as stored fields rather than reconstructed
  from anchors; where exactly the per-cell `06 00 <kind>` record and the f64
  anchor pair sit in that schema).
- Whether `kind` encodes a table style/type beyond distinguishing cell records.
- The trailing `(3, 2)` u32 pair of the table inline object.
