meta:
  id: sdocx_page
  title: Samsung Notes .sdocx <uuid>.page header
  application: Samsung Notes / S Pen SDK
  file-extension: page
  endian: le
  license: CC0-1.0
  imports:
    - sdocx_object_header
doc: |
  A `.sdocx` archive's `<uuid>.page` member. Each page is one `.page` file; the
  header carries page dimensions, the page UUID, and the content bounding box,
  and is followed by a layer/object tree.

  The layer/object tree is structural: object entries carry raw type, child
  count, and blob size, and recursive children follow the blob. The blob itself
  begins with the common object header, modeled by `sdocx_object_header` via a
  substream. Payload internals (strokes, semantic shape/image/text markers) stay
  procedural and are documented in the companion Markdown:

    - layer/object tree     -> docs/format/container/page/README.md
    - common object header  -> docs/format/container/page/object-header.md
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
  tree:
    pos: base
    type: page_tree
    doc: Layer/object tree rooted at the header's `base` offset.
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
  page_hash:
    pos: _io.size - 58
    size: 32
    doc: |
      32-byte page content hash. This is exactly the value pageIdInfo.dat stores
      as the page's `page_hash` (the manifest copies it), which is why that
      manifest hash is not a digest of the raw .page member. Sits immediately
      before the footer signature.
  footer_signature:
    pos: _io.size - 26
    size: 26
    type: str
    encoding: ASCII
    doc: Trailing marker; always "Page for SAMSUNG S-Pen SDK".
types:
  page_tree:
    seq:
      - id: layer_count
        type: u2
      - id: current_layer_index
        type: u2
      - id: layers
        type: layer
        repeat: expr
        repeat-expr: layer_count
  layer:
    seq:
      - id: layer_prefix
        type: u4
      - id: next_offset
        type: u4
      - id: flag1
        type: u1
      - id: flag2
        type: u1
      - id: flag3
        type: u1
      - id: content_flags
        type: u1
      - id: layer_flags
        type: u4
      - id: content_01
        type: u1
        if: (content_flags & 0x01) != 0
      - id: content_02
        size: 4
        if: (content_flags & 0x02) != 0
      - id: content_04_text
        type: utf16_string
        if: (content_flags & 0x04) != 0
      - id: layer_uuid
        type: utf16_string
        if: (content_flags & 0x08) != 0
      - id: modified_time
        type: s8
        if: (content_flags & 0x10) != 0
      - id: content_20
        size: 4
        if: (content_flags & 0x20) != 0
      - id: object_count
        type: u4
      - id: objects
        type: object_entry
        repeat: expr
        repeat-expr: object_count
      - id: layer_hash
        size: 32
  object_entry:
    seq:
      - id: raw_type
        type: u1
      - id: child_count
        type: s2
      - id: blob_size
        type: u4
      - id: blob
        type: sdocx_object_header
        size: blob_size
      - id: children
        type: object_entry
        repeat: expr
        repeat-expr: 'child_count > 0 ? child_count : 0'
  utf16_string:
    seq:
      - id: char_len
        type: u2
      - id: value
        type: str
        size: char_len * 2
        encoding: UTF-16LE
