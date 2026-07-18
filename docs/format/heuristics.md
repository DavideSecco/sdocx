# Heuristics (not part of the decoded format)

Everything here is **calibrated against ground-truth images**, not decoded from
the bytes. It lives in the renderer (`pysdocx/render.py`) and must **never** be
promoted into a `.ksy` or presented as a format fact. Collected in one place so
the format pages can stay honest about where decoded structure ends and visual
calibration begins.

If a value below could be replaced by a decoded field in the future, that is a
good thing — it would graduate to the relevant `container/` page and leave here.

## Typed-text layout (`note.note`)

The *content* of typed text is decoded (see
[typed-text.md](./container/note-note/typed-text.md)); its *placement on the
page* is calibrated:

| Constant | Role |
|---|---|
| `PARA_SPACE_UNIT` (5.0) | space-before/after value → page units (mixed-style fit) |
| `raw_font_size * 40/9 * line_spacing` | document-body line-box advance |
| `10 * 40/9` | decoded top/bottom Common margin → page units |
| `TYPED_TEXT_TODO_MIN_H` (~76.875) | checkbox-control minimum row height |
| `TYPED_TEXT_GLYPH_WIDTH_SCALE` (0.96) | host sans-serif width correction for body wrapping |
| list hanging indents (80/116) | numbered vs bullet/todo body columns at size 11 |
| `*1.36` / `indent*70` | still-calibrated glyph size and indent placement |

Typed-text **pagination** fits whole line boxes inside the decoded Common body's
vertical margins. A bumped line retains the gap immediately before it (for
example a heading's `space_before`); uniform rows begin the next page without
an added gap. The unit conversion and line advances below are exact for the two
controlled Samsung PDF exports, while glyph anchoring and the todo minimum
remain render calibration.

The note body has no decoded page reference. Pysdocx therefore anchors it on
the first otherwise-empty physical page; OpenSdocx mirrors that rule lazily by
choosing the first small/empty `.page` member (≤512 uncompressed bytes), while
excluding pages referenced by structural tables. Pagination slots are relative
to that anchor, not to document page 0. `Allsamsungnotes` pins the important
counterexample: its typed body starts on physical page 5. Common's decoded
character sections correlate with page bands in the controlled samples, but
are not physical page indices: `Mathsolver&Hyperlink` starts in section 0 and
on physical page 2.

### Measured GT audit and controlled PDFs (2026-07-13)

The existing plain and squared GT captures are full-page 905×1280 screenshots,
not perspective-distorted photos. Their matching `.page` geometry is
1600×2262. `pysdocx.measure_typed_text_gt` detects horizontal raster-ink bands,
maps their centres into page coordinates and aligns them with the current
paginated layout. The centre of an ink band is **not claimed to be the true font
baseline**; it is a stable visual anchor for deltas and residual trends.

Run both independent captures with:

```bash
MPLCONFIGDIR=/tmp/matplotlib .venv/bin/python -m pysdocx.measure_typed_text_gt \
  samples/OnlyTextTypeWritten_260701_180427/note.sdocx \
  samples/OnlyTextTypeWritten_260701_180427/gt/photo_2026-07-01_18-06-27.jpg \
  samples/OnlyTextTypeWritten_260701_180427/gt/photo_2026-07-01_18-06-58.jpg

MPLCONFIGDIR=/tmp/matplotlib .venv/bin/python -m pysdocx.measure_typed_text_gt \
  samples/OnlyTextTypeWritten_squared_260703_013624/note.sdocx \
  samples/OnlyTextTypeWritten_squared_260703_013624/gt/photo_2026-07-03_01-38-42.jpg \
  samples/OnlyTextTypeWritten_squared_260703_013624/gt/photo_2026-07-03_01-38-51.jpg
```

The two controlled samples also include vector PDF exports. The tool reads
their positioned text directly with `pdftotext -bbox-layout`:

```bash
MPLCONFIGDIR=/tmp/matplotlib .venv/bin/python -m pysdocx.measure_typed_text_gt \
  samples/OnlyTypeWrittenTextDifferentFont_260713_212408/note.sdocx \
  samples/OnlyTypeWrittenTextDifferentFont_260713_212408/gt.pdf

MPLCONFIGDIR=/tmp/matplotlib .venv/bin/python -m pysdocx.measure_typed_text_gt \
  samples/OnlytextTypewritten-Sistematic-carattere15_260713_212435/note.sdocx \
  samples/OnlytextTypewritten-Sistematic-carattere15_260713_212435/gt.pdf
```

Controlled-PDF findings:

- PDF coordinates scale to `.page` coordinates by exactly `8/3` (600 pt wide
  to 1600 page units), while a stored font size scales to PDF points by `5/3`.
- Default baseline advance is PDF font size × `1.35`, hence stored font size ×
  **6 page units**. The measured pitches are exactly 66, 84, 114 and 384 for
  stored sizes 11, 14, 19 and 64; the uniform size-15 sample is exactly 90.
- An empty paragraph advances by the same line box as the font carried by its
  newline. This explains the requested blank row after every size block.
- The mixed-font sample matches **32/32 page assignments**, distributed
  `[23, 6, 3]`; the uniform sample matches **50/50**, distributed `[24, 24, 2]`.
- PDF ink-centre residuals are constant within each font size (−3.41, +5.36,
  +19.97 and +151.47 page units respectively). Their size dependence identifies
  a remaining glyph-anchor/font-metric problem, not cumulative spacing drift.

`Allsamsungnotes` adds a mixed-style, list-heavy counterexample with both an
in-app GT capture and a vector PDF. Its first sentence is one Samsung line, not
the two rows produced by the uncorrected host `sans-serif`; that artificial wrap
was the entire 66-unit downward shift seen on every following list row. A 0.96
host-width correction preserves the three-line wrap in `OnlyTextTypeWritten`
while keeping this mixed-style sentence whole. After that correction, all 8 PDF
body rows match their page and have vertical RMSE **3.60** page units; the
independent in-app screenshot gives RMSE **4.74** with no unmatched ink rows.

The same GT grounds list hanging columns at stored size 11. Relative to the body
anchor, numbered text starts at +80 page units; bullet and todo text at +116.
Their marker offsets are respectively +0, +40 and +24. The type-5 paragraph
records are byte-identical to `OnlyTextTypeWritten`; the difference was entirely
our former glyph-width-based prefix reservation, not another on-disk variant.

Existing screenshot findings (32 typed visual lines), remeasured after adopting
the flow model:

- The plain and squared captures agree to **≤0.5 screenshot px** (≤0.884 page
  units) on every aligned ink centre. The grid-removal thresholds are therefore
  not driving the result.
- Page 1 has RMSE **7.91** page units. The renderer now retains the continuous
  pre-heading break gap; page 2 begins the heading at predicted y=185 versus an
  observed ink centre of 201.46.
- The three todo rows advance by **77.76** and **75.99** units while numbered and
  bullet rows remain near 66. Their mean, 76.875, is retained as a calibrated
  checkbox-control minimum.

This closes the core line advance, blank-row and page-break model. Remaining
work is narrower: glyph baseline/anchor metrics, independent samples for every
explicit `line_spacing` choice, and paragraph-style/indent calibration.

## Grid/line/dot/oxford template pitches

Background template ids are decoded; their **pitch** is a per-id constant, not
stored in the `.page` (checked — the page is only ~340 bytes). Measured from
905px-wide GT photos in `samples/AllTypeofPageBasic/` (RE 2026-07-09: line
projection for line/grid/oxford rules, blob-centroid clustering for dot
lattices; *1600/905 to page units):

| Constant (`pysdocx/page.py`) | Values |
|---|---|
| `GRID_SPACING_BY_ID` | id 4≈72.5, 5≈102.5, 6≈168.0 (square: row==col) |
| `LINE_SPACING_BY_ID` | id 1≈72.5, 2≈102.5, 3≈168.0 (row/horizontal-rule pitch only) |
| `DOT_SPACING_BY_ID` | id 7≈(72.5, 79.7), 8≈(102.5, 110.0), 9≈(168.0, 174.8) as (row, col) — **not square**, col consistently ~7-10% wider than row |
| `OXFORD_LINE_SPACING` | ≈65.5 (its own constant, not the shared triple above) |
| `OXFORD_MARGIN_X` / `OXFORD_MARGIN_COLOR` | ≈235 page units from left edge; color is a JPEG-averaged approximation from a single photo |

New template ids (e.g. id 10, unseen in any sample so far) would need a new
measured pitch. `GRID_ORIGIN` (the ~44-page-unit top margin) is reused as-is
for line/dot/oxford — not independently re-measured per category.

The **id → category/name** mapping itself (`TEMPLATE_NAMES` in `pysdocx/page.py`,
see [`container/page/README.md`](./container/page/README.md#basic-background-template-ids--decoded-naming-heuristic-pitch))
is a decoded fact, not a heuristic — it comes from user-handwritten labels on
`samples/AlltypeofPageBasic_260709_200911/note.sdocx`, not a pixel measurement. The
*pitches* above are all heuristic/calibrated, same as the original grid ones.

## Rotated text-box wrapping

Rotated in-page text-box **geometry** is decoded (`frame_midpoints`), but the
**line-breaking** inside a rotated box is heuristic: `_text_box_layout` projects
onto the frame midpoints and applies a calibrated inner-wrap inset (`18.0`) for
non-vertical boxes, plus a "move whole styled run to the next line" rule. No
decoded inner-padding field has been found — see
[unknowns.md](./unknowns.md#note-note) and `future_todo.md`.

## Stroke rendering

Rendering-only choices, not format: Catmull-Rom smoothing between decoded points,
pen-width clamps (raised to ~30px for highlighters), and pressure-taper shaping.
The decoded stroke data (points, pressure, width, color) is upstream of all of
these.

## Table rendering (`note.note` type-22 object)

The table's structure is fully decoded (grid, per-cell fill/spans, border blocks —
see [container/note-note/tables.md](./container/note-note/tables.md)); the mapping
of those fields to pixels is render calibration:

- **Grid geometry** uses the wrap bbox + `col_widths`/row heights
  (`note_table_grid`), which are page-local, rather than the cell bboxes (whose Y
  is document-stacked on geometry-edited tables).
- **Border edges from the two 4-entry blocks:** entries 0/2 are vertical, 1/3
  horizontal, and enabled when `argb` is opaque and `width > 0` (decoded). The
  *drawing* rule is calibrated: a boundary edge (frame top/bottom, left/right) is
  drawn when **either** the outer frame **or** the grid enables that direction
  (so "grid horizontal only, no frame" still closes top+bottom); interior lines
  are grid-only; a full frame with `radius > 0` draws as one rounded rect and
  suppresses the straight boundary lines. Line width is a calibrated constant
  (`1.2pt`) — the decoded `width` is `1.0` corpus-wide, so it carries no scale yet.
- **Header/"evidenzia" fill:** a highlighted row/column carries no `fill_argb`;
  it is recognised by its foreground colour `#3a3a3d` (the header ink, vs the body
  default `#252525`) and painted with the table's `theme_fill_argb` (beige). This
  fg→fill link is a heuristic; the fill colour itself is the decoded theme value.
- **Cell font size** is the decoded per-cell `font_size` span, only *shrunk* to
  fit the column (never capped up), so a cell set to 20 renders larger.
- **Under/strike lines** span the measured glyph width, not the whole cell.
