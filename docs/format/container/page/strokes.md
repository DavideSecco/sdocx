# `.page` → stroke payloads

Freehand ink. Each `raw_type == 1` object is a stroke. The record layout is
structural, but the coordinate stream is **delta-compressed**, which is
procedural (a running reconstruction, not a fixed field array) — hence documented
here rather than in a `.ksy`.

- **Reference parser:** `parse_stroke`, `decode_coordinates`, `decode_trailing`,
  `_select_layout`, `_parse_stroke_object` in
  [`pysdocx/page.py`](../../../../pysdocx/page.py).
- **Absolute-f64 diagnostic:** [`spec/tools/analyze_absolute_f64_strokes.py`](../../../../spec/tools/analyze_absolute_f64_strokes.py)
  searches stroke blobs for alternate absolute coordinate runs.
- **Status:** record layout **Structural**; coordinates + channels **Decoded**;
  a couple of geometry constants and tool-id edges are noted below.

## Record layout — Structural

Offsets relative to the stroke record start `off`. `extra_len` =
`total_size - STROKE_OBJECT_BASE_TOTAL_SIZE` (0 for a plain pen stroke).

```
off+0    4 x f64   bbox
off+32   ...        meta block (+extra_len in the "current" layout)
  meta+21  u32      data_len   (byte length of the coordinate+channel blob)
  meta+39  u16      n_points   ("current"), or meta+36 ("shifted")
off+73   2 x f64   start point (x, y)   (off+70 in "shifted")
...      data_len  coordinate deltas + trailing channels
```

### Two layouts — Decoded selection rule
A stroke is stored in one of two layouts: **current**, or **shifted**
(`StartPointMinusThree`, meta/point/start offsets shifted by 3). The parser
decodes both and keeps the one whose reconstructed points are **bbox-consistent**
(`points_fit_bbox`); if both fit, the one with more points wins; if neither,
`current` is used only to advance the stream. This bbox-based selection is what
fixed pages that previously lost handwriting between records.

## Coordinates — Decoded (delta)

The coordinate blob starts at `start point + 16` and is decoded as a running
delta chain seeded by the start point (`decode_coordinates`): each step is a
variable-width delta added to the previous position, `n_points - 1` times. A
coordinate-delta flag bit doubles a delta's resolution — missing this made
straight ("ruler-mode") lines render far too short and at the wrong angle (see
`backlog-ruler-line-precision`). The remaining bytes after the coordinates are
the **trailing channels** (`decode_trailing`).

## Channels — Decoded

Per-stroke and/or per-point: **pressure**, **intensity**, **pen width**,
**color**, and **tool family / taperedness**. The **`tool_id`** is decoded from a
color-marker byte (see `backlog-pen-types`): basic pens have `tool_id ∈ {0,1}`
(and the object-header `flags` bit `0x1 == 0`); extended pens set the extended
header. `tool_id = 6` is a straight-line-capable tool, behaviourally understood
but not formally named.

## Straight-line variant — Marker

Strokes with `extra_len == 48` (`FLAT_LINE_EXTRA_LEN`) and a near-flat bbox are a
distinct "flat synthetic line" variant (the "LINEA DRITTA" straight-line
highlighter/marker). They are recognised structurally and given the corrected
ruler-line geometry.

## Notes on confidence

- **Decoded:** record layout, layout-selection rule, delta reconstruction,
  channel meanings, tool-id from the color marker, the straight-line variant.
- **Heuristic (renderer):** a few geometry constants live in `pysdocx.render`
  (Catmull-Rom smoothing, width clamps) — rendering choices, not format facts.
  See [`../../heuristics.md`](../../heuristics.md).
- **Known open:** a raw-absolute-`f64` coordinate variant was observed on a
  couple of benchmark pages (points stored as absolute pairs, not deltas) that
  neither layout reads; not yet fully decoded. Current diagnostic result:
  `analyze_absolute_f64_strokes.py samples` sees 11,375 stroke objects; 11,353
  are already bbox-consistent under the delta decoder, and scanning the 22
  delta-inconsistent objects finds no count-prefixed or aligned absolute-f64
  point run. This is a negative result for the current corpus, not proof that
  the variant does not exist in future samples.
