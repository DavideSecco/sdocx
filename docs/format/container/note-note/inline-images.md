# `note.note` → inline images

Imported images can be placed **inline in the typed-note body**, not only as
`.page` object-tree objects. These inline placements live in `note.note` and use
the **exact same on-disk record as page-object images** ([page
`object-types.md` → Images](../page/object-types.md#images--raw_type-3)):

- the `01 00 04 20` placement marker,
- a `u16` media index `6` bytes before it (or, preferred, the
  `06 00 3e 00 00 00 02 00` ref-marker → `u32` media index),
- a `4 × f64` bbox `11` bytes after the marker, and
- an edge-midpoint geometry block (the same one page images carry).

Because they sit in the note-doc byte stream — not in any `.page` layer/object
tree — neither the page object walk nor `scan_images_from_objects` ever reaches
them. They are exactly the placements that `mediaInfo.dat`'s `ref_count`
counts **beyond** the page objects.

- **Reference parser:** `scan_note_inline_images` in
  [`pysdocx/note_doc.py`](../../../../pysdocx/note_doc.py) — reuses
  `pysdocx.page.scan_images` verbatim, bounded by the note-doc's own
  `width`/`height` (a tall document-flow canvas). Tags each hit
  `source="note_inline"`.
- **CLI:** `.venv/bin/python -m pysdocx objects <file>` prints a
  `note.note inline images` section after the per-page objects.
- **Corpus gate:** `NoteInlineImageTest` in
  [`tests/test_pysdocx_regressions.py`](../../../../tests/test_pysdocx_regressions.py)
  — **zero counterexamples**: only two samples carry inline images, every other
  corpus `note.note` scans to zero (no spurious marker matches).

## Decoded

- **Media reference** and **bbox** — decoded byte-exactly (same record as page
  images). On `ImagesAllTrasnsformations` the four inline placements resolve to
  media `0, 0, 3, 0`; on `quiz`, one placement to media `7` (a real `.png`).
- Ground-truth accounting on `ImagesAllTrasnsformations`: **6 page-object images
  + 4 inline = 10**, matching the user's count and `mediaInfo.dat`'s
  `ref_count` (media `0` = 9 → 6 page + 3 inline; media `3` = 1 → 0 page + 1
  inline).

## Page placement — Decoded (bbox) + Heuristic (page)

Each inline image anchors at a **U+FFFC character position** in the body Common
frame (it appears as an `object_type == 3` entry in `body["inline"]["objects"]`,
alongside tables=22 and web=13). The body text carries `sections`
(`(char_start, char_length)` ranges) that track **page bands**, so:

> **host page = index of the `sections` interval containing the image's anchor
> char** (chars past the last section fall back to the last section), clamped to
> the document's page count; **position within the page = the stored `01 00 04 20`
> bbox**, which is already **page-local** (its origin aligns with the page-object
> coordinates — the top inline `y=44` matches the page-object top image `y=44`).

On `ImagesAllTrasnsformations` this yields a **1-image / 3-image** split across the
two content pages, matching the user's ground-truth annotations exactly (page 1:
"IMMAGINE ANCORATA"; page 2: "FIT TO PAGE WIDTH" / "LOCK" / "EDITA con sticker"
[media 3] / "CROP dell'angolo"). Parsers: `note_inline_image_placements`
(pysdocx) / `note_doc::note_inline_images` (Rust, populates
`DocumentMetadata::note_inline_images`); rendered by `render.py` and the OpenSdocx
scene builder.

The **section→page map is a heuristic** (the note body has no hard page
reference), calibrated on this one rich sample and cross-listed in
[`../../heuristics.md`](../../heuristics.md#inline-image-placement). The `quiz`
sample (1 page, 1 inline image whose anchor char is past its single section) is
handled by the clamp; its stored bbox `y` is not page-local, so its render
position on the single page is approximate.

**Affine transform** (rotation/scale from the edge-midpoint geometry) is
available via the same `_derive_affine_transform` path as page images, but the
corpus inline images are all upright, so they render axis-aligned; affine can be
wired in if a rotated-inline sample ever appears.

**Crop** applies to inline images too (same flex fields as page objects — see
[object-types.md → Images](../page/object-types.md#images--raw_type-3)): the
page-1 "CROP dell'angolo" inline is a top-right-corner crop (aspect 2.786),
decoded by `note_inline_image_placements` and rendered as an image source-rect.
