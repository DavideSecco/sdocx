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
- **Decoded — placed-frame affine (rotation + scale):** the
  [payload-geometry wrapper](./payload-geometry.md) decoded for every image
  stores four points that are the placed frame's **edge midpoints**, in order
  `[top, right, bottom, left]` — the **same convention as text-box frames**, not
  corners. `pysdocx.page._derive_affine_transform` reconstructs the placed
  rectangle's corners from the midpoints (`center = ½(top+bottom)`, half-width
  vector `= right − center`, half-height `= top − center`), then solves the
  affine mapping the axis-aligned bbox corners onto them (`x' = a·x + c·y + e`,
  `y' = b·x + d·y + f`); the 4th reconstructed corner is a closure check. Images
  without a valid quad fall back to angle-only rendering.
  - On `samples/ImagesAllTrasnsformations_260713_221310` the derived matrices are
    pure rotations relative to the bbox: the 45° image →
    `a=d=0.707, b=0.707, c=-0.707` (cos/sin 45°), the 270° image → `a=d=0,
    b=-1, c=1`, and every `angle=0` image → identity. Size differences between
    placements are carried by the bbox itself, not by scale in the matrix.
  - **Correction (2026-07-18):** an earlier version of this note claimed the quad
    proved shear/skew — citing "unequal half-diagonal magnitudes (66.08 vs
    231.05)" on object idx=51. That was a misread: those are the half-**height**
    and half-**width** of a non-square (462×132) image's edge midpoints, not
    diagonals. Treating the midpoints as corners silently produced a spurious
    ~45° "inscribed diamond" shear (an angle=0 image derived a heavy shear and
    still passed the closure check, because a parallelogram's edge midpoints also
    form a parallelogram). No shear is present in the corpus.
- **Decoded — crop rect.** In the flex fields after the media ref, a field-flag
  byte's `0x40` bit marks a **cropped** image; when set, a `4×f64` rect gives
  where the **full (uncropped) image would sit on the page** (its aspect equals
  the source image's). The placement bbox is the cropped window inside that rect,
  so the visible source sub-rect is the placement bbox normalized into it —
  exposed as a normalized `crop {x,y,w,h}` (source fractions) by
  `pysdocx.page._image_crop` / Rust `page::image_crop`, and drawn as an
  image source-rect. Offsets (`IMAGE_CROP_FLAG_FWD=57`, `IMAGE_CROP_RECT_FWD=90`
  after the media ref) are calibrated on the two cropped images in
  `ImagesAllTrasnsformations` (a page-object crop, aspect 3.076, and a note.note
  inline crop of the top-right corner, aspect 2.786); the derived crops reproduce
  those aspects and match the "CROPPA su X e Y" / "CROP dell'angolo" ground truth.
  Applies to note.note [inline images](../note-note/inline-images.md) too. The
  crop flex is Kaitai-gated by
  [`spec/ksy/sdocx_image_object.ksy`](../../../../spec/ksy/sdocx_image_object.ksy)
  (`validate_image_object.py`, 69/69 image records, the crop bit clear on all 67
  uncropped — zero counterexamples).
- `sdocx2pdf` exposes a still-broader Image flex schema (original rect, border,
  ratio, `original_image_bind_id`); those remain **Unknown**. See
  `spec/tools/analyze_sdocx2pdf_leads.py`.
- **Inline (typed-note) images:** the identical `01 00 04 20` record also appears
  in `note.note`, for images anchored in the body text rather than a page object
  tree — these are invisible to the page object walk. See
  [note-note/inline-images.md](../note-note/inline-images.md).

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
- **Decoded — full Text wrapper + `text_core::Common` (16/16):** every text-box blob
  carries the same rich-text frame as the note body
  ([typed-text](../note-note/typed-text.md#the-text_corecommon-frame--decoded)),
  reached structurally by `pysdocx.note_doc.parse_text_wrapper` through
  `ObjectBase(0) → ShapeBase(6) → Shape(7).flex_offset`, and Kaitai-gated by
  `sdocx_text_wrapper.ksy`: the frame text is
  the scanned text plus its trailing empty-paragraph newlines, and the
  enabled bold/italic/underline spans equal the scanned runs on 16/16 boxes.
  The frame sits at blob offset **386** on every non-rotated box and **406**
  on every rotated one. The 20-byte delta is ObjectBase `angle` (f32) plus
  `pivot` (2×f64), shifting the payload-geometry block by the same amount.
  Frame margins are `[8, 4, 8, 4]` (left/top/right/bottom) on 16/16 —
  the box's stored inner text padding; gravity is 0 (top). After the frame,
  a fixed 48-byte tail: `text_auto_fit_type` (1 byte), the 15-byte Text frame,
  then a 32-byte hash-like value (Unknown; not plain SHA-256 of the prefix).
- **All-octant rotation sample (2026-07-11):**
  `TextboxAllAngles_260709_231912.sdocx` contains boxes at
  `0/45/90/135/180/225/270/315°`; 315° is stored as `-45.0f`. Every nonzero
  angle, including 180°, sets header bit `0x1` and adds the same 20-byte wrapper
  region; 0° omits both. The four geometry midpoints stay centred on the bbox
  but can extend outside it at 90°/270°, confirming that projected midpoints,
  not the axis-aligned bbox, carry the box's local extents. The sample text is
  only `Text`, so this validates rotation geometry but cannot calibrate wrapping.
- **Heuristic (not format):** how a rotated box wraps its text — the 90° and 16°
  boxes are laid out with a calibrated inner-wrap inset, not the decoded
  `[8, 4, 8, 4]` margins above (the renderer has not been reconciled with them
  yet). See [`../../heuristics.md`](../../heuristics.md) and `future_todo.md`.
- Unknown: only the construction/semantics of the final 32-byte hash-like
  trailer and some constant ShapeBase fields; wrapper boundaries and fields
  used by current text boxes are decoded.

## Attachments on a page — Marker / Inferred

- **Sticky-note property bags** Structural + Semantic (media index, attachment
  type-tag, bag keys, collapse bbox), read from page bytes.
- **Audio / non-sticky placements**: on the dedicated GT sample, the pages meant
  to host sticky-notes and an audio recording have a **completely empty object
  tree** — so no per-page placement is known for these yet; they are surfaced via
  the archive-level [attachment manifest](../mediaInfo.md) instead.
- Unknown: a structural page-object model for attachment placement in all cases;
  full recursive decode of nested sticky-note `.sdocx`.
