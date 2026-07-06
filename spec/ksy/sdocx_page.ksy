meta:
  id: sdocx_page
  title: Samsung Notes .sdocx <uuid>.page header
  application: Samsung Notes / S Pen SDK
  file-extension: page
  endian: le
  license: CC0-1.0
doc: |
  The fixed header of a `.sdocx` archive's `<uuid>.page` member. Each page is one
  `.page` file; the header carries page dimensions, the page UUID, and the
  content bounding box, and is followed by a layer/object tree.

  Only the header is modeled here. The layer/object tree, the common object
  header (its `field_flags` additive size model), the non-stroke payload-geometry
  wrapper, and the stroke payloads (delta-compressed coordinates — procedural)
  are documented in the companion Markdown:

    - object tree + header  -> docs/format/container/page/object-header.md
    - payload geometry       -> docs/format/container/page/payload-geometry.md
    - strokes                -> docs/format/container/page/strokes.md
    - shapes/images/text     -> docs/format/container/page/object-types.md

  The `template` (grid/plain) is not a single fixed field — its offset depends on
  `base` and the note's source (built-in vs imported PDF) — so it is decoded
  procedurally and documented, not modeled here. The named fields below hold with
  zero counterexamples across the 13-sample corpus.
seq:
  - id: base
    type: u4
    doc: Header base/layout selector at offset 0.
instances:
  page_width:
    pos: 0x16
    type: u4
    doc: Page width in page units.
  page_height:
    pos: 0x1a
    type: u4
    doc: Page height in page units.
  uuid_char_len:
    pos: 0x26
    type: u2
    doc: UTF-16 character count of the page UUID.
  uuid:
    pos: 0x28
    type: str
    size: uuid_char_len * 2
    encoding: UTF-16LE
    doc: Page UUID; matches this member's filename and a pageIdInfo.dat record.
  content_bbox:
    pos: 0x80
    type: f8
    repeat: expr
    repeat-expr: 4
    doc: Content bounding box [x_min, y_min, x_max, y_max] as f64.
