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
  A `.sdocx` archive's `<uuid>.page` member. Each page is one `.page` file.

  The header (bytes `0 .. base`) is a sequential structure: `base` (the
  layer-tree start offset, alias `page_end_offset`), `flex_offset`, two
  variable-length bitfields, page geometry/uuid/timestamps, then a run of
  optional "flex" fields gated by one `field_flags` bit each, in bit order,
  starting exactly at `flex_offset`. It is followed by the layer/object tree
  at `base`, and a trailing page hash + SDK signature.

  Field names cross-referenced from squ1dd13/sdocx2pdf (MIT) — `page.rs`,
  `page/header.rs` — re-validated field-by-field on the local corpus before
  adoption here (zero counterexamples, 214/214 pages,
  spec/tools/validate_page_header.py; see docs/format/xref-sdocx2pdf.md and
  docs/format/container/page/README.md). Reference Python parser:
  pysdocx/page_header.py (this .ksy mirrors it field-for-field).

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

  Two fields deliberately not resolved further here (still Marker/Unknown,
  see docs/format/unknowns.md): `template_type` ids 10/12-15 are named from
  sdocx2pdf only, not yet grounded against a hand-labeled sample of our own;
  and `custom_object`'s `trailing_raw` (constant 8 bytes on the corpus,
  semantics Unknown — sdocx2pdf's own schema doesn't have this field).
seq:
  - id: base
    type: u4
    doc: |
      Page-end / layer-tree-start offset (alias page_end_offset). Relative to
      the header start, which is absolute since the header begins at 0.
  - id: flex_offset
    type: u4
    doc: Absolute offset where the field-flags-gated optional region begins.
  - id: property_flags
    type: var_bitfield
    doc: Bit 0 = is_text_only (sdocx2pdf name; corpus semantics untested here).
  - id: field_flags
    type: var_bitfield
    doc: |
      Each set bit gates one optional field below, in bit order. Modeled
      bits: 0-12, 15, 16, 18 (sdocx2pdf names; bits 13, 14, 17 are gaps in
      their own numbering, not modeled by them either). Observed on the
      corpus: 0, 2, 3, 4, 5, 6, 8, 9, 10, 11, 18.
  - id: orientation
    type: u4
  - id: width
    type: u4
    doc: Page width in page units.
  - id: height
    type: u4
    doc: Page height in page units.
  - id: offset_x
    type: u4
  - id: offset_y
    type: u4
  - id: uuid
    type: short_utf16
    doc: Page UUID; matches this member's filename and a pageIdInfo.dat record.
  - id: modified_time_us
    type: s8
    doc: Modified time, epoch microseconds.
  - id: format_version
    type: u4
  - id: min_format_version
    type: u4
  - id: drawn_rect
    type: f8
    repeat: expr
    repeat-expr: 4
    if: has_drawn_rect
    doc: |
      [x_min, y_min, x_max, y_max]; present iff the layer tree declares
      objects (proven equivalent to that gate on 226/226 pages). Alias
      content_bbox.
  - id: tags
    type: tag_list
    if: has_tags
  - id: template_uri
    type: short_utf16
    if: has_template_uri
    doc: Custom-image template path; supersedes the page_custom_template_uri heuristic.
  - id: background_image_id
    type: s4
    if: has_background_image_id
  - id: background_image_mode
    type: u4
    if: has_background_image_mode
    doc: 0 centre, 1 stretch, 2 fit, 3 tile (sdocx2pdf names).
  - id: background_colour
    size: 4
    if: has_background_colour
    doc: BGRA, alpha == 0xFF. Matches page_background_color's heuristic, 226/226.
  - id: background_width
    type: u4
    if: has_background_width
  - id: background_rotation
    type: u4
    if: has_background_rotation
  - id: pdf_data_items
    type: pdf_data_items(format_version)
    if: has_pdf_data_items
    doc: |
      Embedded-PDF page placements. Matches page_pdf_template's heuristic on
      every single-entry case (25/25); also finds a 20-entry tiled-import
      page the heuristic misses entirely (samples/cs61bl_su22).
  - id: template_type
    type: u4
    if: has_template_type
    doc: |
      17-variant enum (see docs/format/container/page/README.md). Matches
      the "Basic" template id from page_template's heuristic id-for-id
      everywhere both fire.
  - id: canvas_cache_map
    type: canvas_cache_map
    if: has_canvas_cache_map
  - id: imported_data_height
    type: u4
    if: has_imported_data_height
  - id: theme
    type: u4
    if: has_theme
    doc: sdocx2pdf calls this "skipped by the libs". Semantics Unknown.
  - id: recognised_data_modified_time_us
    type: s8
    if: has_recognised_data_modified_time
  - id: stroke_recognition_data
    type: opaque_blob_list
    if: has_stroke_recognition_data
  - id: custom_objects
    type: custom_object_list
    if: has_custom_objects
    doc: |
      Sticky notes (object_type 1) and forward-compatible others. Matches
      scan_sticky_notes' marker-scan heuristic on media_index and
      skn_collapse_rect; also surfaces skn_bg_color, never extracted before.
instances:
  tree:
    pos: base
    type: page_tree
    doc: Layer/object tree rooted at the header's `base` offset.
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
  has_drawn_rect:
    value: (field_flags.value >> 0) & 1 != 0
  has_tags:
    value: (field_flags.value >> 1) & 1 != 0
  has_template_uri:
    value: (field_flags.value >> 2) & 1 != 0
  has_background_image_id:
    value: (field_flags.value >> 3) & 1 != 0
  has_background_image_mode:
    value: (field_flags.value >> 4) & 1 != 0
  has_background_colour:
    value: (field_flags.value >> 5) & 1 != 0
  has_background_width:
    value: (field_flags.value >> 6) & 1 != 0
  has_background_rotation:
    value: (field_flags.value >> 7) & 1 != 0
  has_pdf_data_items:
    value: (field_flags.value >> 8) & 1 != 0
  has_template_type:
    value: (field_flags.value >> 9) & 1 != 0
  has_canvas_cache_map:
    value: (field_flags.value >> 10) & 1 != 0
  has_imported_data_height:
    value: (field_flags.value >> 11) & 1 != 0
  has_theme:
    value: (field_flags.value >> 12) & 1 != 0
  has_recognised_data_modified_time:
    value: (field_flags.value >> 15) & 1 != 0
  has_stroke_recognition_data:
    value: (field_flags.value >> 16) & 1 != 0
  has_custom_objects:
    value: (field_flags.value >> 18) & 1 != 0
  has_unhandled_field_bits:
    value: field_flags.value & 0xfffa6000 != 0
    doc: |
      True if any field bit outside the modeled set (0-12, 15, 16, 18) is
      set; the sequence after min_format_version would then be misaligned.
      Zero on the corpus.
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
    instances:
      has_objects:
        value: 'layers.size > 0 and layers[0].object_count > 0'
        doc: Current corpus has one layer; its declared object count gates the preamble content_bbox.
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
  var_bitfield:
    doc: |
      `[u8 n_bytes][n-byte little-endian bitfield]`, n <= 4. On the corpus n
      is 1 (property_flags) or 4 (field_flags).
    seq:
      - id: len
        type: u1
      - id: b0
        type: u1
        if: len >= 1
      - id: b1
        type: u1
        if: len >= 2
      - id: b2
        type: u1
        if: len >= 3
      - id: b3
        type: u1
        if: len >= 4
    instances:
      value:
        value: >-
          (len >= 1 ? b0 : 0) | (len >= 2 ? b1 << 8 : 0) |
          (len >= 3 ? b2 << 16 : 0) | (len >= 4 ? b3 << 24 : 0)
  short_utf16:
    doc: A u16 character count followed by that many UTF-16LE code units.
    seq:
      - id: char_len
        type: u2
      - id: value
        type: str
        size: char_len * 2
        encoding: UTF-16LE
  short_utf8:
    doc: A u16 BYTE count followed by that many UTF-8 bytes (object uuids in this region).
    seq:
      - id: byte_len
        type: u2
      - id: value
        type: str
        size: byte_len
        encoding: UTF-8
  long_utf8:
    doc: A u32 byte count followed by that many UTF-8 bytes.
    seq:
      - id: byte_len
        type: u4
      - id: value
        type: str
        size: byte_len
        encoding: UTF-8
  tag_list:
    seq:
      - id: count
        type: u2
      - id: tags
        type: short_utf16
        repeat: expr
        repeat-expr: count
  pdf_data_items:
    params:
      - id: format_version
        type: u4
    seq:
      - id: count
        type: u2
      - id: items
        type: pdf_page_item(format_version)
        repeat: expr
        repeat-expr: count
  pdf_page_item:
    params:
      - id: format_version
        type: u4
    doc: |
      `rect` is 4×f64 pre-2034 format versions, else 4×i32 (both variants
      agree with page_pdf_template's media/page indices on every corpus page
      where both mechanisms fire).
    seq:
      - id: file_id
        type: u4
      - id: page_index
        type: u4
      - id: rect_f64
        type: f8
        repeat: expr
        repeat-expr: 4
        if: format_version < 2034
      - id: rect_i32
        type: s4
        repeat: expr
        repeat-expr: 4
        if: format_version >= 2034
  canvas_cache_map:
    seq:
      - id: entry_count
        type: u4
      - id: entry_size
        type: u2
      - id: entries
        type: canvas_cache_entry
        repeat: expr
        repeat-expr: entry_count
        if: entry_size == 49
      - id: raw_entries
        size: entry_count * entry_size
        if: entry_size != 49
        doc: |
          A size other than 49 means a newer app struct we don't model;
          entries are skipped raw rather than misread. Unseen on the corpus.
  canvas_cache_entry:
    doc: 49 bytes total (4-byte key + 45-byte entry).
    seq:
      - id: key
        type: u4
      - id: file_id
        type: u4
      - id: width
        type: u4
      - id: height
        type: u4
      - id: is_dark_mode
        type: u1
      - id: background_colour
        size: 4
      - id: version
        type: u4
        repeat: expr
        repeat-expr: 3
      - id: cache_version
        type: u4
      - id: property
        type: u4
      - id: locale_list_id
        type: u4
      - id: system_font_path_hash
        type: u4
  opaque_blob_list:
    seq:
      - id: count
        type: u4
      - id: blobs
        type: opaque_blob
        repeat: expr
        repeat-expr: count
  opaque_blob:
    seq:
      - id: size
        type: u4
      - id: data
        size: size
  custom_object_list:
    seq:
      - id: count
        type: u4
      - id: objects
        type: custom_object
        repeat: expr
        repeat-expr: count
  custom_object:
    seq:
      - id: object_type
        type: u4
        doc: 1 == sticky_note (CustomObjectType::StickyNote); other ids unseen on the corpus.
      - id: size
        type: u4
      - id: body
        type: custom_object_body
        size: size
  custom_object_body:
    seq:
      - id: reserved
        type: u4
      - id: property_flags
        type: var_bitfield
      - id: field_flags
        type: var_bitfield
      - id: uuid
        type: short_utf8
      - id: attached_files
        type: string_to_u4_map
        doc: '"co_attach_file" -> media bind id on the corpus.'
      - id: custom_data
        type: string_to_string_map
        doc: |
          "skn_collapse_rect" ("x0,y0,x1,y1" page-coordinate string) and
          "skn_bg_color" (signed-decimal Android ARGB colour string) on the
          corpus. NOTE: skn_collapse_rect and this type's own `rect` field
          below are two DIFFERENT bounding boxes on every observed instance
          — which is the true on-page icon placement is unresolved, see
          docs/format/unknowns.md.
      - id: rect
        type: f8
        repeat: expr
        repeat-expr: 4
      - id: trailing_raw
        size-eos: true
        doc: |
          Unknown. sdocx2pdf's own schema ends at `rect`, but every corpus
          instance (3/3) carries exactly 8 more bytes here, decoding as two
          u32s both equal to 5303 — constant across two unrelated notes, so
          plausibly a version/build tag from a newer Samsung Notes build
          than sdocx2pdf's author saw.
  string_to_u4_map:
    seq:
      - id: count
        type: u4
      - id: entries
        type: string_to_u4_entry
        repeat: expr
        repeat-expr: count
  string_to_u4_entry:
    seq:
      - id: key
        type: long_utf8
      - id: value
        type: u4
  string_to_string_map:
    seq:
      - id: count
        type: u4
      - id: entries
        type: string_to_string_entry
        repeat: expr
        repeat-expr: count
  string_to_string_entry:
    seq:
      - id: key
        type: long_utf8
      - id: value
        type: long_utf8
