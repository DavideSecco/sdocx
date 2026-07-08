# `note.note` → tables

Table content lives in `note.note` (not in the `.page` ink tree): the table is
an **inline object of type 22** embedded in the body text's `text_core::Common`
frame, and every cell is a **nested Common frame** of its own — see
[typed-text](./typed-text.md#table-cells-and-inline-objects). The table object
anchors at a U+FFFC char in the body text.

- **Structural parser:** `parse_table_object` / `note_doc_tables` in
  [`pysdocx/note_doc.py`](../../../../pysdocx/note_doc.py) — parses the whole
  object body **byte-exactly** (every sub-record size lands, the content
  region lands on the object end). Cross-checked against the render marker
  scan (`parse_tables`) on grid shape, per-position cell text, anchors,
  column widths, and bbox by
  [`spec/tools/analyze_note_doc.py`](../../../../spec/tools/analyze_note_doc.py):
  **2/2 table notes, 18/18 cells, zero counterexamples** (and zero type-22
  objects elsewhere in the corpus).
- **Reference parser (render path):** `parse_tables` / `_cell_style` in
  [`pysdocx/note.py`](../../../../pysdocx/note.py) (marker scan — now fully
  explained by the structural schema, see below).
- **Presence:** there is **no dedicated has-tables flag**. `meta_flags` bit
  `0x2000` gates `voice_data` ([README](./README.md#field_flags-alias-meta_flags--decoded));
  tables are present iff the body frame has an inline object of type 22.
- **Status:** the object's **framing is Decoded end-to-end**; geometry
  (bboxes, column widths, row heights, outlines) is **Decoded**; the style
  tail's field *positions* are Decoded but their *semantics* (which border is
  which, the three floats, the f32 arrays) are **Unknown** pending a
  styled-table sample family.

## Object layout — Decoded

Two size conventions coexist. **Self-sized** records carry a `u32 size` that
counts from the size field's own offset; **chain** records (rows, cells,
paths, border blocks) carry a `u32 size` counting the bytes *after* the field.
Recurring byte tokens (Marker): `T5 = 01 00 02 00 00`, `PRE9 = u32 0 + T5`,
`TOKEN15 = 0f 00 00 00 02 00 00 00 00 00 + T5`.

```
table object body (obj_size bytes)
├─ wrap        [self-sized, 126]   u16 0, u32 105, 8B, u32 version (5400),
│                                  u16 36 + ASCII uuid, i64 ts1_us, f64×4 bbox
│                                  (page coords), 5B zeros, i64 ts2_us,
│                                  u32 page_width (1600), u32 0, u8 3,
│                                  u32 n_rows-1
├─ midpoints   [self-sized, 91]    u16 tag 6 … u32 4 + 4×(f64,f64): the edge
│                                  midpoints of the table rect (text coords)
├─ outline     [self-sized, 135]   u16 tag 7 … + path of the table rect
│                                  (text coords)
└─ content     [self-sized]        lands exactly on the object end:
   ├─ u16 22 (the object type), u16 15, u16 0, 3B `01 04 02`, u16 7612
   ├─ u32 n_cols + n_cols × f32 col_width
   ├─ u32 n_rows, then per row [chain]:
   │    PRE9, f32 row_height, u32 row_index, u32 n_cols,
   │    then per cell [chain]:
   │      PRE9, u32 col_index, u32 1, u32 1, u32 0,
   │      f64×4 cell bbox (page coords), u8 1,
   │      u32 inner_size (== rest of the cell), then:
   │      ├─ wrap      [self-sized, 113]  as above but version 4000,
   │      │                               per-cell uuid, ts 0, same bbox,
   │      │                               no ts2/trailing fields
   │      ├─ midpoints [self-sized, 130]  cell edge midpoints (page coords)
   │      │                               + 19B sub-record (holds u32 255)
   │      │                               + 16B tail (u32 12 + zeros) — Unknown
   │      ├─ outline   [self-sized]       cell rect path (page coords),
   │      │                               then the cell's Common frame,
   │      │                               then 2B `00 02`
   │      └─ TOKEN15   (cell terminator)
   └─ style tail:
        f64×4 table bbox again, border block A, u32 n_cols + n_cols × f32,
        u32 n_cols + n_cols × f32, f32 scalar, border block B, u32 ARGB
```

**Paths** are `[u32 size(chain)][u32 n_ops]` + opcodes: `01` = moveto
(f64 x, f64 y), `02` = lineto (f64 x, f64 y), `06` = closepath (no point).
Corpus paths are all closed 4-corner rectangles.

**Border blocks** are `[u32 size(chain)][u32 0][T5]` + 4 × `[u32 ARGB]
[f32][f32][f32]`. On the corpus: color `ffb1ac98` everywhere; block A floats
`(1.0, 26.0, 26.0)`, block B `(1.0, 0.0, 0.0)`; the final ARGB is `ffeeebe7`.
Border/float semantics **Unknown** (defaults never varied).

**Timestamps:** `ts1_us ≥ ts2_us` on both corpus tables, epoch microseconds
in the note's edit window — modified/created candidates (Marker, not
promoted: 2 observations).

## The legacy scan marker, explained

The scan's 10-byte "cell record" `[f64 x][f64 y][u16 6][…frame]` is the tail
of the cell's **outline path**: `(x, y)` is the last lineto point (the cell's
bottom-left corner — hence the anchor semantics), `06` is the **closepath
opcode**, the following `00` is the outline record's pad byte, and the
scanned "kind" (`0x8d`/`0x95`/`0xcd`…) is the low byte of the cell frame's
own `frame_size`. The former "constant 461-byte inter-record block" =
17B cell trailer (`00 02` + TOKEN15) + next cell's chain header and
sub-records; the "25-byte row record" = `u32 row_size + PRE9 + f32 height +
u32 row_index + u32 n_cols`.

## Cell rich text — Decoded

A cell's styling is the span vector of its own Common frame, with cell-local
coordinates (`start = 0`, `end = char_count`). The render path reads the same
bytes as local TLV runs scoped to the cell and accepts only runs matching the
cell exactly, so a run overrunning into the next cell cannot be
mis-attributed. Bold/italic/underline, color, and font size are read this way;
a plain cell simply carries only the default color+font spans.

## What is Unknown

- The semantics of the style tail: which border block / entry maps to which
  border, the three floats per border (width + two more), the two per-column
  f32 arrays (291.2 / 1456.0 on the corpus), the trailing scalar (1456.0 ==
  table width here) and final ARGB (`ffeeebe7`).
- The wrap record's 8 head bytes, `u16 7612`, content head `01 04 02`, the
  midpoints record's `base`/`flags` fields (0/1 at table level, 91/0x0c01 at
  cell level), the cell midpoints' 19-byte + 16-byte sub-records, and the
  outline `base` (0 / 135).
- Merged cells, custom borders/widths/heights, cell background colors: never
  observed. Needs a table-only sample family (plain grid / merged cells /
  custom borders + widths + shading) to vary these one at a time.
