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
  ADDITIVE `field_flags` size model (zero counterexamples across the corpus):

    0x1     ANGLE      +4   rotation-angle f32 at offset 105
    0x20    EXTRA_KEY  +32  "extra_key_stroke_shape" attribute block
    0x40000 HDR_EXT    +16  [counter, seq, page_width, page_height]
    0x8000  MEDIA_FAMILY  0 image/shape/drawing discriminator (no size)
    0x2000|0x4000 BASE   0  present on every object

  The three size-contributing blocks are stored in bit order (angle, then
  extra_key, then hdr_ext), so this type reads them in that order. Payload data
  after the header (strokes, geometry wrappers) is NOT read here.

  Corpus invariants baked in: `flag_len == 2` and `field_len == 4` on all 11788
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
    if: (field_flags & 0x20) != 0
  - id: hdr_ext
    type: header_ext
    if: (field_flags & 0x40000) != 0
types:
  extra_key_block:
    doc: 32-byte named attribute block; identical on 40/40 objects that set 0x20.
    seq:
      - id: head
        size: 3
        doc: Constant 02 01 00.
      - id: key_len
        type: u2
        doc: Key length; 23 (22 chars + NUL).
      - id: key
        type: str
        size: key_len
        encoding: ASCII
        doc: The ASCII key extra_key_stroke_shape plus a NUL; marks a shape's ink.
      - id: trailing
        type: u4
        doc: Constant 1.
  header_ext:
    doc: 16-byte extension; page_width/height match the page header 1690/1690.
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
