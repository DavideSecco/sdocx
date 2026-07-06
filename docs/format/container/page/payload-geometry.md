# `.page` → non-stroke payload-geometry wrapper

Non-stroke inserted objects (shapes, images, in-page text boxes) begin their
payload — right after the common object header — with a small geometry wrapper.
Decoded corpus-wide (**412/412** wrapper-bearing objects), so it is a first-class
parser field (`obj["payload_geometry"]`).

- **Reference parser:** `_decode_payload_geometry`, `_shape_payload_geometry_role`
  in [`pysdocx/page.py`](../../../../pysdocx/page.py).
- **Status:** wrapper layout + point geometry **Decoded**; per-shape point role
  **Marker / Inferred**.

## Wrapper layout — Decoded

```
u32  L0                      length field 0
u16  tag = 6
u32  L1                      length field 1
01 00 01 0c                  geometry opcode
u32  point_count
point_count x (f64 x, f64 y) coordinate pairs
```

Corpus coverage: **412** wrappers — `shape` 390, `image` 15, `text_box` 7.

### Marker offset equations — Decoded

The later semantic marker for each family sits at a fixed delta from the wrapper
lengths (measured from `total_size`), holding exactly on the corpus:

- **image**: `dL0 = 0`, `dL1 = 0` on 15/15
- **shape** (marker-based): `dL0 = 0`, `dL1 = 0` on 337/337
- **text box**: UTF-16 text marker at `total + L1 + 172` (`dL0 = 123`,
  `dL1 = 0`) on 7/7

Text-box frame geometry now reads from this wrapper first, replacing scattered
offset constants.

## Point roles — Marker / Inferred

The point list is interpreted per shape family. This is a **structural
interpretation of the wrapper points, not the render source of truth** (the
rendered outline still comes from the shape marker's path when available):

| Role | Shapes |
|---|---|
| outline vertices | ellipse, hexagon, rhombus, pentagon |
| frame edge-midpoints | rectangle, trapezoid, cross, rounded-rect |
| vertices + edge-midpoints | triangle |
| star outer vertices | star |
| freeform / control points | freeform |
| arrow shaft endpoints | arrow |

### Caveat — centroid match is not universal
For image and text-box frames, the point centroid matches the bbox centre (a
semantic check). It is **not** universal for every shape variant:
`bbox_centroid_match = 301`, `mismatch = 103`, `unknown = 8`. So centroid-match
is used where it holds, not promoted as a global invariant, and the point roles
are corpus-backed rather than claimed for all future Samsung shape families.
