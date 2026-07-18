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
  [`spec/tools/analyze_note_doc.py`](../../../../spec/tools/analyze_note_doc.py)
  — **zero counterexamples** (and zero type-22 objects elsewhere in the
  corpus). The `Tabella4x3Regolare` samples add a controlled styled-table
  family (base + row/column highlight + font size + bold + strikethrough +
  text colour + per-cell background + changed column widths + the v2 border
  family: sharp 90° corners, no vertical lines, top/bottom only, no borders,
  a 10×4 grid with empty cells, and an invisible all-off 5×2), one variable
  per page, each with rendered-PDF ground truth.
- **Executable spec:** [`spec/ksy/sdocx_table_object.ksy`](../../../../spec/ksy/sdocx_table_object.ksy)
  models the whole object (wrap, geometry, rows/cells, nested Common frames
  with spans/paragraphs, style tail) and is cross-checked field-by-field
  against `parse_table_object` by
  [`spec/tools/validate_table_object.py`](../../../../spec/tools/validate_table_object.py),
  gated in `tests/test_kaitai_spec.py` (`test_table_object`).
- **Reference parser (render path):** `parse_tables` / `_cell_style` in
  [`pysdocx/note.py`](../../../../pysdocx/note.py) (marker scan — now fully
  explained by the structural schema, see below).
- **Presence:** there is **no dedicated has-tables flag**. `meta_flags` bit
  `0x2000` gates `voice_data` ([README](./README.md#field_flags-alias-meta_flags--decoded));
  tables are present iff the body frame has an inline object of type 22.
- **Status:** the object's **framing is Decoded end-to-end**; geometry
  (bboxes, column widths, row heights, outlines) is **Decoded**; **per-cell
  character styling** (font size, bold, strikethrough, foreground colour), the
  **per-cell background fill**, and — via the v2 border family — the **style
  tail's border blocks** (outer frame + inner grid lines, with per-edge ARGB,
  stroke width and corner radii) are all **Decoded and ground-truth
  confirmed**. Remaining Unknowns are minor (see the list at the end).

## Object layout — Decoded

Two size conventions coexist. **Self-sized** records carry a `u32 size` that
counts from the size field's own offset; **chain** records (rows, cells,
paths, border blocks) carry a `u32 size` counting the bytes *after* the field.
Recurring byte tokens (Marker): `T5 = 01 00 02 00 00`, `PRE9 = u32 0 + T5`,
`TOKEN15 = 0f 00 00 00 02 00 00 00 00 00 + T5`. At the **cell** level the
`PRE9` marker's 2nd `T5` byte is a **styled flag** (`01` when the table
carries any explicit styling, `00` on a fully default table) — i.e. the cell
preamble is `u32 0 + 01 <styled> 02 00 00`.

```
table object body (obj_size bytes)
├─ wrap        [self-sized, 126]   u16 0, u32 105, 8B, u32 version (5400),
│                                  u16 36 + ASCII uuid, i64 ts1_us, f64×4 bbox
│                                  (page coords), 5B zeros, i64 ts2_us,
│                                  u32 page_width (1600), u32 0, u8 3,
│                                  u32 table_index (see note below)
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
   │      PRE9 (with styled flag), u32 col_index, u32 1, u32 1,
   │      u32 cell_fill_argb (0xAARRGGBB, 0 = no fill),
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
        f64×4 table bbox again,
        border block OUTER (the table frame),
        u32 n_cols + n_cols × f32 col_width_min (291.2 = 1456/5 — Marker),
        u32 n_cols + n_cols × f32 col_width_max (1456.0 — Marker),
        f32 table_width_max (1456.0 = note width − 2×72 margins),
        border block GRID (the inner lines),
        u32 theme_fill_argb (ffeeebe7 — the theme's header/highlight beige)
```

**Paths** are `[u32 size(chain)][u32 n_ops]` + opcodes: `01` = moveto
(f64 x, f64 y), `02` = lineto (f64 x, f64 y), `06` = closepath (no point).
Corpus paths are all closed 4-corner rectangles.

**Border blocks — Decoded** (v2 border family, one variant per page, PDF
ground truth). Each block is `[u32 size(chain)][u32 0][T5]` + 4 ×
`[u32 ARGB][f32 width][f32 radius_x][f32 radius_y]`:

- The **first** block is the table's **outer frame**, the **second** the
  **inner grid lines**.
- In each block, entries **0/2 are the vertical** edges/lines and **1/3 the
  horizontal** ones. The two members of a pair have never differed, so
  left-vs-right and top-vs-bottom remain unresolved. (Evidence: "solo bordo
  superiore e inferiore" = outer `[off, ON, off, ON]`, grid all off;
  "no bordi verticali" = outer all off, grid `[off, ON, off, ON]` — the app
  draws grid horizontals on every row boundary.)
- The two radii are the **rounded-corner radii**: `26.0` on the default outer
  frame, `0` on "bordi netti a 90°" and always `0` on grid lines.
- A **disabled border is fully zeroed** (`00000000`, width 0): "nessun bordo"
  zeroes both blocks. Default colour is `ffb1ac98` (warm grey), width `1.0`.
- The trailing `theme_fill_argb` (`ffeeebe7` beige) and the width-constraint
  arrays stayed constant across every variant — theme values, not state.

**Timestamps:** `ts1_us ≥ ts2_us` on every corpus table, epoch microseconds
in the note's edit window — modified/created candidates (Marker, not promoted).

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

## Cell character styling — Decoded, ground-truth confirmed

A cell's character styling is the span vector of its own Common frame, with
cell-local coordinates (`start = 0`, `end = char_count`). Each span is
`[u16 rec_size][u32 span_type][u32 start][u32 end][u32 interval_type][extra]`.
A plain cell carries exactly two spans — `font_size` and `foreground_color`;
styling adds more. The `Tabella4x3Regolare` family isolates one attribute per
page, confirming the `text_core` span types (previously named only from
`sdocx2pdf`) against rendered PDF ground truth:

| `span_type` | meaning | `extra` payload | ground-truth page |
|---|---|---|---|
| 3  | `font_size`        | f32 pt (`15.0` default, `20.0` on the size-20 column) | col 2 = carattere 20 |
| 5  | `bold`             | u32 bool (`1` = on)                | col 1 = grassetto |
| 6  | `italic`           | u32 bool (only `0` observed)       | — |
| 7  | `underline`        | u32 bool (only `0` observed)       | — |
| 20 | `strikethrough`    | u8 bool (`1` = on) + 3 residue bytes, 20-byte record | last row = cancellata |
| 1  | `foreground_color` | little-endian `0xAARRGGBB`         | row 3 = azzurro (`ff3396ff`) |

Each span-payload also carries a constant trailing `u32 0`. The `interval_type`
is `1` throughout. The "evidenzia riga/colonna" **header highlight** (base +
row / column / L-shape pages) is *not* a per-cell fill: the highlighted cells
keep `cell_fill_argb == 0` and are marked instead by a full header-style span
set — `bold=1`, `italic=0`, `underline=0`, `strikethrough=0`, plus a distinct
header text colour (`ff3a3a3d`). Its beige backing is a theme constant, drawn
by the app, not stored per cell (Heuristic — see below).

## Cell background fill — Decoded

A manually set cell background ("sfondo" colour) is stored in the cell's
`cell_fill_argb` field (little-endian `0xAARRGGBB`, `0` = no fill). On the
`sfondo blu` column it holds `ffdaecfb` (light blue), matching the rendered
PDF; every other cell in the corpus is `0`.

## What is Unknown

- **Within a border pair**, which entry is left vs right / top vs bottom (the
  pair members have never differed). Custom border *colours/widths* have not
  been observed either — the UI only toggles borders on/off and corner style —
  so `width` is confirmed only by its zeroing when a border is off.
- The `col_width_min`/`col_width_max` arrays and `table_width_max` are named
  from their values (291.2 = 1456/5 with the app's 5-column cap; 1456 = the
  drawable width) but never varied — **Marker**, not promoted.
- The beige backing of an "evidenzia" header matches `theme_fill_argb`
  (`ffeeebe7`), which stayed constant everywhere — the link is **Heuristic**;
  a theme that recolours the header would confirm it.
- The wrap record's 8 head bytes, `u16 7612`, content head `01 04 02`, the
  midpoints record's `base`/`flags` fields (0/1 at table level, 91/0x0c01 at
  cell level), the cell midpoints' 19-byte + 16-byte sub-records, and the
  outline `base` (0 / 135).
- Merged cells: the UI does not expose a merge action, so likely N/A. Custom
  row heights: not yet observed (all corpus rows are 126.0). Column widths
  **do** vary and are Decoded as the `col_width` f32 array; empty cells are
  simply empty Common frames (10×4 sample); an "invisible" table (all borders
  off, all cells empty) parses like any other (the v2 ghost 5×2).
- **Cell-bbox Y origin (Marker, 3 hits / 17 non-hits).** A cell's `bbox` and
  the table wrap `bbox` normally share a page-local Y origin (they differ by
  ~0.5). On the tables whose **grid geometry was edited after insertion**
  (dragged column widths ×2, added rows/columns on the 10×4), the cell bboxes
  are instead shifted down by exactly `page_index × page_height`
  (dy = 4.00 / 4.00 / 10.00 pages) — a **document-stacked** Y origin — while
  the wrap bbox stays page-local. Width/height and X match exactly either way,
  so a renderer should treat cell-bbox Y relative to the wrap bbox, never as
  absolute.
- **`table_index` is really the 0-based host PAGE index (Marker → Decoded, zero
  counterexamples).** Named "table index / document order" when first decoded,
  but the value is the index of the page the table is anchored to, not the
  table's ordinal among the note's tables: `Allsamsungnotes` has a **single**
  table with `table_index = 3` and its ground-truth page is **page 4** (index
  3) — an ordinal would be 0. On the styled family it increments one-per-page
  (0..5 / 0..10), and the two tables of the geometry-edited `v2` note that share
  a page **both** carry `table_index = 10`. It also equals the stacked-Y
  multiplier above (dy = `table_index × page_height`). This is note.note's
  missing table→page reference: a renderer places each table on
  `pages[table_index]` (the wrap bbox is page-local, so its X/Y are the on-page
  rect directly). No `table_index ≥ page_count` case exists in the corpus. (The
  decode-layer field keeps the `table_index` name for now; renamed only in the
  render/placement layer.)
