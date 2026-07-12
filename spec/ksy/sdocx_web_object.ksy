meta:
  id: sdocx_web_object
  title: Samsung Notes type-13 Web inline object
  endian: le
  license: CC0-1.0
doc: |
  Body of a type-13 object embedded in a text_core::Common inline-object
  vector. It consists of a generic ObjectBase inclusive frame followed by a
  type-13 inclusive flex frame. Field 7 is present in the sole corpus instance
  but its semantics are unknown, so it remains an opaque exclusive frame.
seq:
  - id: object_base_size
    type: u4
  - id: object_base_raw
    size: object_base_size - 4
  - id: frame_size
    type: u4
  - id: frame
    type: web_frame
    size: frame_size - 4
instances:
  consumes_eof:
    value: _io.pos == _io.size
types:
  var_bitfield:
    seq:
      - id: len
        type: u1
      - id: raw
        size: len
    instances:
      value:
        value: >-
          (len >= 1 ? raw[0] : 0) | (len >= 2 ? raw[1] << 8 : 0) |
          (len >= 3 ? raw[2] << 16 : 0) | (len >= 4 ? raw[3] << 24 : 0)
  short_utf16:
    seq:
      - id: char_len
        type: u2
      - id: value
        type: str
        size: char_len * 2
        encoding: UTF-16LE
  opaque_exclusive:
    seq:
      - id: byte_size
        type: u4
      - id: raw
        size: byte_size
  web_frame:
    seq:
      - id: object_type
        type: u2
        valid: 13
      - id: flex_offset
        type: u4
      - id: property_flags
        type: var_bitfield
      - id: field_flags
        type: var_bitfield
      - id: attached_html_file_id
        type: u4
        if: field_flags.value & 1 != 0
      - id: thumbnail_file_id
        type: u4
        if: field_flags.value & 2 != 0
      - id: body
        type: short_utf16
        if: field_flags.value & 4 != 0
      - id: title
        type: short_utf16
        if: field_flags.value & 8 != 0
      - id: uri
        type: short_utf16
        if: field_flags.value & 16 != 0
      - id: image_type_id
        type: u4
      - id: version
        type: u4
        if: field_flags.value & 32 != 0
      - id: view_type
        type: u4
        if: field_flags.value & 64 != 0
      - id: field_7_opaque
        type: opaque_exclusive
        if: field_flags.value & 128 != 0
    instances:
      flex_offset_matches:
        value: flex_offset == 12 + property_flags.len + field_flags.len
      has_unhandled_field_flags:
        value: field_flags.value & 0xffffff00 != 0
