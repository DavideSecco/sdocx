meta:
  id: sdocx_object_header
  title: Samsung Notes .sdocx common object header (one object blob)
  application: Samsung Notes / S Pen SDK
  endian: le
  license: CC0-1.0
doc: |
  The common header at the start of every object in a `.page` layer/object tree.
  Fed one object blob (the bytes from an object entry's stored size). The base
  header is a fixed layout ending at offset 105; its length then grows by an
  `field_flags`-gated extension model:

    0x1     ANGLE      +4   rotation-angle f32 at offset 105
    0x20    EXTRA_BUNDLE generic ObjectBase property bag
    0x40000 HDR_EXT    +16  [counter, seq, page_width, page_height]
    0x8000  MEDIA_FAMILY  0 image/shape/drawing discriminator (no size)
    0x2000|0x4000 BASE   0  present on every object

  The extensions are stored in bit order (angle, then extra_key, then hdr_ext).
  The extra-bundle block consumes the bytes up to the optional final 16-byte
  HDR_EXT. Payload data
  after the header (strokes, geometry wrappers) is NOT read here.

  Corpus invariants baked in: `flag_len == 2` and `field_len == 4` on all
  objects, and `uuid_len == 36`, which is what makes the base header land exactly
  at 105. A future variant that breaks these would surface as a test-gate
  mismatch against pysdocx.
seq:
  - id: total_size
    type: u4
    doc: Full header size; reconstructed additively from field_flags.
  - id: data_type
    type: s2
    doc: Raw object type (1=stroke, 2=text_box, 3=image, 7/8=shape, 14=drawing).
  - id: var_data_offset
    type: u4
    doc: Offset to the object's variable/payload data (105 on the corpus).
  - id: flag_len
    type: u1
    doc: Length of the flags field; always 2 on the corpus.
  - id: flags
    type: u2
    doc: Capability field. 0x1bf on non-stroke objects; on strokes bit 0x1 varies.
  - id: field_len
    type: u1
    doc: Length of the field_flags field; always 4 on the corpus.
  - id: field_flags
    type: u4
    doc: The additive size-model flags (see the type doc).
  - id: format_version
    type: u4
  - id: uuid_len
    type: s2
    doc: Byte length of the UTF-8 UUID; 36 on the corpus.
  - id: uuid
    type: str
    size: uuid_len
    encoding: UTF-8
  - id: modified_time
    type: s8
    doc: Object modified time (epoch ms).
  - id: bbox
    type: f8
    repeat: expr
    repeat-expr: 4
    doc: Object bounding box [x_min, y_min, x_max, y_max]; starts at offset 68.
  - id: timestamp
    type: u4
  - id: resizable
    type: u1
  # --- field_flags-gated extensions, in total_size-bit order (offset 105+) ---
  - id: angle_deg
    type: f4
    if: (field_flags & 0x1) != 0
    doc: Rotation angle in degrees (clockwise on screen).
  - id: extra_key
    type: extra_key_block
    size: 'extra_key_head != 2 ? total_size - _io.pos - ((field_flags & 0x40000) != 0 ? 16 : 0) - 16 : 32'
    if: (field_flags & 0x20) != 0
  - id: hdr_ext
    type: header_ext
    if: (field_flags & 0x40000) != 0
  - id: math_header_tail
    size: 16
    if: (field_flags & 0x20) != 0 and extra_key_head != 2
    doc: Constant zero padding after Math Solver's property bag / HDR_EXT.
instances:
  extra_key_head:
    pos: '105 + ((field_flags & 0x1) != 0 ? 4 : 0)'
    type: u1
    if: (field_flags & 0x20) != 0
types:
  extra_key_block:
    doc: |
      Generic ObjectBase bundle/property bag (sdocx2pdf `Bundle`): a one-byte
      presence bitfield gates string, u32, string-vector and byte-buffer maps.
      Older notes called the first three bytes a `head`; in this model those
      bytes are simply `presence_flags + u16 map_count`.
    seq:
      - id: presence_flags
        type: u1
      - id: string_prop_count
        type: u2
        if: (presence_flags & 0x1) != 0
      - id: string_props
        type: string_property
        repeat: expr
        repeat-expr: string_prop_count
        if: (presence_flags & 0x1) != 0
      - id: integer_prop_count
        type: u2
        if: (presence_flags & 0x2) != 0
      - id: integer_props
        type: integer_property
        repeat: expr
        repeat-expr: integer_prop_count
        if: (presence_flags & 0x2) != 0
      - id: string_vec_prop_count
        type: u2
        if: (presence_flags & 0x4) != 0
      - id: string_vec_props
        type: string_vec_property
        repeat: expr
        repeat-expr: string_vec_prop_count
        if: (presence_flags & 0x4) != 0
      - id: byte_vec_prop_count
        type: u2
        if: (presence_flags & 0x8) != 0
      - id: byte_vec_props
        type: byte_vec_property
        repeat: expr
        repeat-expr: byte_vec_prop_count
        if: (presence_flags & 0x8) != 0
  ascii_key:
    seq:
      - id: byte_count
        type: u2
      - id: value
        type: str
        size: byte_count
        encoding: ASCII
  string_property:
    seq:
      - id: key
        type: ascii_key
      - id: value
        type: utf16_string
  integer_property:
    seq:
      - id: key
        type: ascii_key
      - id: value
        type: u4
  string_vec_property:
    seq:
      - id: key
        type: ascii_key
      - id: string_count
        type: u2
      - id: strings
        type: utf16_string
        repeat: expr
        repeat-expr: string_count
  byte_vec_property:
    seq:
      - id: key
        type: ascii_key
      - id: byte_count
        type: u4
      - id: value
        size: byte_count
  utf16_string:
    seq:
      - id: char_count
        type: u2
      - id: value
        type: str
        size: char_count * 2
        encoding: UTF-16LE
  named_u32_property:
    seq:
      - id: separator
        type: u2
        doc: Constant 1 between chained Math Solver properties.
      - id: key_len
        type: u2
      - id: key
        type: str
        size: key_len
        encoding: ASCII
      - id: value
        type: u4
  named_string_array_property:
    seq:
      - id: separator
        type: u2
        doc: Constant 1 between chained Math Solver properties.
      - id: key_len
        type: u2
      - id: key
        type: str
        size: key_len
        encoding: ASCII
      - id: string_count
        type: u2
      - id: strings
        type: utf16_string
        repeat: expr
        repeat-expr: string_count
  header_ext:
    doc: 16-byte extension; page_width/height match every corpus page header.
    seq:
      - id: counter
        type: u4
        doc: Groups related/copied objects; not a unique id (Unknown).
      - id: seq
        type: u4
        doc: Near-constant per note; not per-object, not monotonic (Unknown).
      - id: page_width
        type: u4
      - id: page_height
        type: u4
