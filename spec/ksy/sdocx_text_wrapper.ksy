meta:
  id: sdocx_text_wrapper
  title: Samsung Notes Text / Shape wrapper
  application: Samsung Notes / S Pen SDK
  endian: le
  license: CC0-1.0
  imports:
    - sdocx_table_object
    - sdocx_web_object
doc: |
  Complete inheritance chain used by note.note title/body Text blobs and by
  raw type-2 page text boxes:

    ObjectBase(type 0) -> ShapeBase(type 6) -> Shape(type 7) -> Text(type 2)

  Every component is an inclusive-length ObjectHeader frame.  Shape's flex
  offset lands directly on its text_core::Common frame, so the main rich-text
  payload is parsed without marker scanning.  Page text boxes may append one
  32-byte hash-like value after Text; note.note title/body blobs end at Text.
seq:
  - id: object_base
    type: object_base_frame
  - id: shape_base
    type: opaque_frame(6)
  - id: shape
    type: shape_frame(object_base.body.format_version)
  - id: text
    type: text_frame
  - id: trailing_hash_like
    size: _io.size - _io.pos
types:
  bitfield:
    seq:
      - id: n_bytes
        type: u1
      - id: raw
        size: n_bytes
    instances:
      value:
        value: 'raw[0] + (n_bytes > 1 ? raw[1] << 8 : 0) + (n_bytes > 2 ? raw[2] << 16 : 0) + (n_bytes > 3 ? raw[3] << 24 : 0)'
  object_header:
    seq:
      - id: data_type
        type: u2
      - id: flex_offset
        type: u4
      - id: property_flags
        type: bitfield
      - id: field_flags
        type: bitfield
  object_base_frame:
    seq:
      - id: size
        type: u4
      - id: body
        type: object_base_body
        size: size - 4
  object_base_body:
    seq:
      - id: header
        type: object_header
      - id: format_version
        type: u4
      - id: uuid_len
        type: u2
      - id: uuid
        type: str
        size: uuid_len
        encoding: UTF-8
      - id: modified_time_us
        type: s8
      - id: bbox
        type: f8
        repeat: expr
        repeat-expr: 4
      - id: timestamp
        type: u4
      - id: resize_mode
        type: u1
      - id: angle_deg
        type: f4
        if: (header.field_flags.value & 1) != 0
      - id: append_time_us
        type: s8
        if: (header.field_flags.value & 0x2000) != 0
      - id: owner_page_size
        type: u4
        repeat: expr
        repeat-expr: 2
        if: (header.field_flags.value & 0x4000) != 0
      - id: pivot
        type: f8
        repeat: expr
        repeat-expr: 2
        if: (header.field_flags.value & 0x40000) != 0
  opaque_frame:
    params:
      - id: expected_type
        type: u2
    seq:
      - id: size
        type: u4
      - id: body
        type: opaque_body(expected_type)
        size: size - 4
  opaque_body:
    params:
      - id: expected_type
        type: u2
    seq:
      - id: header
        type: object_header
      - id: fixed_and_flex
        size: _io.size - _io.pos
  shape_frame:
    params:
      - id: format_version
        type: u4
    seq:
      - id: size
        type: u4
      - id: body
        type: shape_body(format_version)
        size: size - 4
  shape_body:
    params:
      - id: format_version
        type: u4
    seq:
      - id: header
        type: object_header
      - id: shape_type
        type: u4
      - id: original_rect
        type: f8
        repeat: expr
        repeat-expr: 4
      - id: original_angle
        type: f4
      - id: path_size
        type: u4
      - id: path
        size: path_size
      - id: control_point_count
        type: u1
      - id: control_points
        type: point
        repeat: expr
        repeat-expr: control_point_count
      - id: common_size
        type: u4
        if: (header.field_flags.value & 1) != 0
      - id: common
        type: common_frame
        size: common_size
        if: (header.field_flags.value & 1) != 0
      - id: shape_field_11_f32
        type: f4
        if: (header.field_flags.value & 0x800) != 0
      - id: ellipsis_type
        type: u1
        if: (header.field_flags.value & 0x1000) != 0
      - id: text_auto_fit_type
        type: u1
        if: (header.field_flags.value & 0x2000) != 0
  text_frame:
    seq:
      - id: size
        type: u4
      - id: body
        type: text_body
        size: size - 4
  text_body:
    seq:
      - id: header
        type: object_header
      - id: border_colour
        size: 4
        if: (header.field_flags.value & 2) != 0
      - id: border_width
        type: f4
        if: (header.field_flags.value & 4) != 0
      - id: border_type
        type: u2
        if: (header.field_flags.value & 8) != 0
  point:
    seq:
      - id: x
        type: f8
      - id: y
        type: f8
  common_frame:
    seq:
      - id: char_count
        type: u4
      - id: text_utf16
        type: str
        size: char_count * 2
        encoding: UTF-16LE
      - id: span_count
        type: u4
      - id: spans
        type: span_rec
        repeat: expr
        repeat-expr: span_count
      - id: paragraph_count
        type: u4
      - id: paragraphs
        type: paragraph_rec
        repeat: expr
        repeat-expr: paragraph_count
      - id: margins
        type: f4
        repeat: expr
        repeat-expr: 4
      - id: gravity
        type: u1
      - id: section_count
        type: u2
      - id: sections
        type: section_pair
        repeat: expr
        repeat-expr: section_count
      - id: inline_present
        type: u4
      - id: inline_zero
        type: u4
      - id: inline_count
        type: u4
        if: inline_present != 0
      - id: inline_objects
        type: inline_object
        repeat: expr
        repeat-expr: inline_count
        if: inline_present != 0
  span_rec:
    seq:
      - id: size
        type: u2
      - id: span_type
        type: u4
      - id: start
        type: u4
      - id: end
        type: u4
      - id: interval_type
        type: u4
      - id: extra
        size: size - 16
  paragraph_rec:
    seq:
      - id: size
        type: u2
      - id: paragraph_type
        type: u4
      - id: start
        type: u4
      - id: end
        type: u4
      - id: extra
        size: size - 12
  section_pair:
    seq:
      - id: first
        type: u4
      - id: second
        type: u4
  inline_object:
    seq:
      - id: frame_size
        type: u4
      - id: frame
        type: inline_object_body
        size: frame_size
  inline_object_body:
    doc: |
      `object_body` is decoded for the two known inline-object types (22 =
      table, 13 = web link/preview); other types (e.g. 3 = inline image)
      have no dedicated spec yet and stay opaque bytes.
    seq:
      - id: object_size
        type: u4
      - id: object_type
        type: u4
      - id: object_body
        size: object_size
        type:
          switch-on: object_type
          cases:
            22: sdocx_table_object
            13: sdocx_web_object
            _: opaque_inline_body
      - id: position
        type: u4
      - id: tail
        size: _io.size - _io.pos
  opaque_inline_body:
    seq:
      - id: raw
        size-eos: true
