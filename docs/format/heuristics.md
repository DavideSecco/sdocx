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
| `PARA_SPACE_UNIT` (~4.9) | space-before/after value → pixels |
| `TYPED_TEXT_BLANK_H` (~75) | empty-paragraph height (least certain; one GT) |
| `TYPED_TEXT_PAGE_PAD` | page padding used in pagination |
| `TYPED_TEXT_LINE_H` (~66) | base line height |
| `*1.36` / `/1.35` / `indent*70` | assorted layout scale factors |

Typed-text **pagination** (bumping a whole line that would cross the page bottom
to the next page) mirrors observed Samsung behaviour but the trigger geometry is
calibrated, not read from a field. Calibrated against
`OnlyTextTypeWritten_squared_260703_013624.sdocx` (grid GT).

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
`samples/AlltypeofPageBasic_260709_200911.sdocx`, not a pixel measurement. The
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
