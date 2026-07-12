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
    0x20    EXTRA_KEY  variable-sized named property block
    0x40000 HDR_EXT    +16  [counter, seq, page_width, page_height]
    0x8000  MEDIA_FAMILY  0 image/shape/drawing discriminator (no size)
    0x2000|0x4000 BASE   0  present on every object

  The extensions are stored in bit order (angle, then extra_key, then hdr_ext).
  The extra-key block consumes the bytes up to the optional final 16-byte
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
    doc: Variable-sized named property. Values are decoded by their 3-byte head.
    seq:
      - id: head
        size: 3
        doc: 02 01 00 for scalar values; 04 01 00 for string arrays.
      - id: key_len
        type: u2
        doc: ASCII key byte length including its NUL terminator.
      - id: key
        type: str
        size: key_len
        encoding: ASCII
        doc: NUL-terminated ASCII property name.
      - id: trailing
        type: u4
        if: head == [2, 1, 0]
        doc: Scalar value; 1 for extra_key_stroke_shape.
      - id: string_count
        type: u2
        if: head == [4, 1, 0]
      - id: strings
        type: utf16_string
        repeat: expr
        repeat-expr: string_count
        if: head == [4, 1, 0]
      - id: math_expression
        type: utf16_string
        if: head == [7, 1, 0]
      - id: math_fail_code
        type: u4
        if: head == [6, 1, 0]
      - id: fail_property
        type: named_u32_property
        if: head == [7, 1, 0]
      - id: uuid_property
        type: named_string_array_property
        if: head == [6, 1, 0] or head == [7, 1, 0]
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
