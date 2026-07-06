meta:
  id: sdocx_payload_geometry
  title: Samsung Notes .sdocx non-stroke payload-geometry wrapper
  application: Samsung Notes / S Pen SDK
  endian: le
  license: CC0-1.0
doc: |
  The geometry wrapper that begins the payload of a non-stroke inserted object
  (shape, image, in-page text box), immediately after the common object header
  (i.e. at object-blob offset `total_size`). Fed that payload slice.

  Decoded corpus-wide: 412/412 wrapper-bearing objects (shape 390, image 15,
  text_box 7). Only the wrapper header + coordinate points are modeled here; the
  later semantic markers (shape/image/text) and per-shape point roles are marker-
  scanned and documented in docs/format/container/page/payload-geometry.md.
seq:
  - id: l0
    type: u4
    doc: Length field 0.
  - id: tag
    type: u2
    doc: Constant 6.
  - id: l1
    type: u4
    doc: Length field 1.
  - id: opcode
    size: 4
    doc: Geometry opcode; constant 01 00 01 0c.
  - id: point_count
    type: u4
  - id: points
    type: point
    repeat: expr
    repeat-expr: point_count
    doc: Coordinate pairs; role per shape family is documented, not modeled.
types:
  point:
    seq:
      - id: x
        type: f8
      - id: y
        type: f8
