# `.page` → shapes, images, drawings, text boxes

The non-stroke object families in the layer/object tree. All share the
[common object header](./object-header.md) and (except drawings) the
[payload-geometry wrapper](./payload-geometry.md); this page covers what is
type-specific.

- **Reference parser:** `parse_shapes_from_objects`, `scan_images_from_objects`,
  `scan_drawings_from_objects`, `parse_text_boxes_from_objects`,
  `scan_attachment_placements`, `scan_sticky_notes` in
  [`pysdocx/page.py`](../../../../pysdocx/page.py).

## Shapes — `raw_type` 7 / 8

- **Membership** Structural; **visual geometry** largely Semantic; some internals
  Marker / Inferred.
- Decoded: type classification, outline geometry, closed/open handling,
  width/color, arrows / freeform / regular shapes. Outline comes from the shape
  marker's path; the [payload-geometry](./payload-geometry.md) point roles give a
  structural read of the frame.
- Unknown: a complete formal schema for every shape payload variant.

## Images — `raw_type` 3

- **Placement / rotation / media ref** Semantic.
- Decoded: image placement bbox, media index, rotation angle (via `field_flags`
  `0x1`, [see the header page](./object-header.md#0x1-angle--rotation-f32--105)).
- The media index maps to a `media/<index>@…` archive member (and a
  [`mediaInfo.dat`](../mediaInfo.md) record). Placement markers: `01 00 04 20`
  with a `u16` media index just before and a 4×`f64` on-page bbox just after.
- `sdocx2pdf` exposes a broader Image flex schema (crop/original/border fields).
  Our current diagnostic confirms that the already-decoded media reference is
  present as a `u32` in every image object blob (15/15), but does **not** yet
  isolate which flex field corresponds to `original_image_bind_id` or the crop
  fields. See `spec/tools/analyze_sdocx2pdf_leads.py`.

## Drawings — `raw_type` 14

- **Membership** Structural; **media linkage / placement** Marker / Inferred.
- Decoded: drawing media placement from object/blob markers; raster drawing
  rendering when the media is a raster. Drawings do **not** share the
  payload-geometry wrapper in the current corpus.
- `sdocx2pdf` calls raw type 14 `Painting`. Our current diagnostic confirms the
  drawing media reference as a `u32` in the one corpus painting/drawing object
  (1/1), but the attached thumbnail, ratio, crop rect, and original rect remain
  hypotheses until a larger corpus validates them.
- Unknown: fuller object-level semantics for the drawing/painting payload.

## Text boxes — `raw_type` 2

- **Text / rich text / angle** Semantic; **rotated frame geometry** largely
  Semantic; **inner text layout** partial.
- Decoded: text content, local style runs (same TLV markers as
  [typed text](../note-note/typed-text.md)), colors / highlights / font sizes,
  rotation angle, and `frame_midpoints` for rotated boxes (from the
  [payload-geometry wrapper](./payload-geometry.md), text marker at
  `total + L1 + 172`).
- **Heuristic (not format):** how a rotated box wraps its text — the 90° and 16°
  boxes are laid out with a calibrated inner-wrap inset, not a decoded padding
  field. See [`../../heuristics.md`](../../heuristics.md) and `future_todo.md`.
- `sdocx2pdf`'s `text_core::Common` frame is visible in 1/7 current text-box
  blobs (`[u32 frame_size][u32 char_count][UTF-16 text]` matching our text
  extraction). The other 6/7 text boxes do not expose that simple frame at the
  same level, so `Common` is a useful lead but not yet promoted here.

## Attachments on a page — Marker / Inferred

- **Sticky-note property bags** Structural + Semantic (media index, attachment
  type-tag, bag keys, collapse bbox), read from page bytes.
- **Audio / non-sticky placements**: on the dedicated GT sample, the pages meant
  to host sticky-notes and an audio recording have a **completely empty object
  tree** — so no per-page placement is known for these yet; they are surfaced via
  the archive-level [attachment manifest](../mediaInfo.md) instead.
- Unknown: a structural page-object model for attachment placement in all cases;
  full recursive decode of nested sticky-note `.sdocx`.
