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

## Grid template pitches

Grid template ids are decoded; their **pitch** is a per-id constant, not stored
in the `.page` (checked — the page is only ~340 bytes). `GRID_SPACING_BY_ID` maps
each known id (e.g. id 5 ≈ 102.5, id 4 ≈ 72.5 page units). New template ids would
need a new measured pitch.

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
