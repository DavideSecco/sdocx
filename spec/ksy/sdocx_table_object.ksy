meta:
  id: sdocx_table_object
  title: Samsung Notes .sdocx type-22 table inline object
  application: Samsung Notes / S Pen SDK
  endian: le
  license: CC0-1.0
doc: |
  The body of a type-22 inline object (a table) embedded in the body text's
  `text_core::Common` frame inside `note.note`. Fed the object-body slice
  (`obj_size` bytes starting at the object's `body_off`).

  Decoded end-to-end and cross-checked field-by-field against
  `pysdocx.note_doc.parse_table_object` by `spec/tools/validate_table_object.py`
  (zero counterexamples on the corpus, including the Tabella4x3Regolare styled
  family with rendered-PDF ground truth). Narrative:
  docs/format/container/note-note/tables.md.

  Two size conventions coexist: SELF-SIZED records carry a `u4 size` counting
  from the size field's own offset; CHAIN records (rows, cells, paths, border
  blocks) carry a `u4 size` counting only the bytes after the field.

  Tables exist only in notes with `format_version >= 2035` (they *are* inline
  objects, which that version introduced), so the nested cell Common frames
  always carry the inline-object fields — no format-version parameter needed.
seq:
  - id: wrap
    type: table_wrap_rec
    doc: Self-sized object wrapper (tag 105).
  - id: midpoints
    type: table_midpoints_rec
    doc: |
      Self-sized midpoints record (tag 6): the 4 edge midpoints of the table
      rect in text coordinates.
  - id: outline
    type: table_outline_rec
    doc: |
      Self-sized outline record (tag 7): the table rect as a closed path in
      text coordinates.
  - id: content_size
    type: u4
    doc: Self-sized; `content_size` bytes from this field land on object end.
  - id: content
    type: table_content
    size: content_size - 4
types:
  table_wrap_rec:
    seq:
      - id: size
        type: u4
      - id: body
        type: table_wrap
        size: size - 4
  table_wrap:
    seq:
      - id: pad
        type: u2
      - id: tag
        type: u4
        doc: Constant 105.
      - id: head
        size: 8
        doc: Semantics Unknown.
      - id: version
        type: u4
        doc: 5400 on table wraps (corpus).
      - id: uuid_len
        type: u2
        doc: Constant 36.
      - id: uuid
        type: str
        size: 36
        encoding: ASCII
      - id: ts1_us
        type: s8
        doc: Epoch microseconds.
      - id: bbox
        type: rect
        doc: Page coordinates.
      - id: zeros5
        contents: [0, 0, 0, 0, 0]
      - id: ts2_us
        type: s8
        doc: Epoch microseconds, <= ts1_us on the corpus.
      - id: page_width
        type: u4
        doc: The note width (1600 on the corpus).
      - id: zero
        type: u4
      - id: b3
        type: u1
        doc: Constant 3.
      - id: table_index
        type: u4
        doc: |
          0-based index of the PAGE this table is anchored to — note.note's
          otherwise-missing table->page reference (not the table's ordinal among
          the note's tables). Evidence: the single-table `Allsamsungnotes` note
          carries 3 and its table is on page 4; per-page styled tables increment
          one-per-page; two tables sharing a page share the value; it equals the
          document-stacked cell-bbox Y multiplier (page_index * page_height).
          Kept the `table_index` name for continuity; it is the page index.
  cell_wrap_rec:
    seq:
      - id: size
        type: u4
      - id: body
        type: cell_wrap
        size: size - 4
  cell_wrap:
    doc: As `table_wrap` but without the trailing ts2/b3/table_index fields.
    seq:
      - id: pad
        type: u2
      - id: tag
        type: u4
        doc: Constant 105.
      - id: head
        size: 8
      - id: version
        type: u4
        doc: 4000 on cell wraps (corpus).
      - id: uuid_len
        type: u2
      - id: uuid
        type: str
        size: 36
        encoding: ASCII
      - id: ts1_us
        type: s8
        doc: 0 on cell wraps.
      - id: bbox
        type: rect
        doc: Page coordinates; equals the enclosing cell's bbox.
      - id: zeros5
        contents: [0, 0, 0, 0, 0]
      - id: page_width
        type: u4
      - id: zero
        type: u4
  table_midpoints_rec:
    seq:
      - id: size
        type: u4
      - id: body
        type: table_midpoints
        size: size - 4
  table_midpoints:
    seq:
      - id: tag
        type: u2
        doc: Constant 6.
      - id: base
        type: u4
        doc: 0 at table level, 91 at cell level (Unknown semantics).
      - id: one
        type: u2
      - id: flags
        type: u2
        doc: 1 at table level, 0x0c01 at cell level (Unknown).
      - id: point_count
        type: u4
        doc: Constant 4.
      - id: points
        type: point
        repeat: expr
        repeat-expr: point_count
      - id: four
        type: u4
      - id: zeros5
        contents: [0, 0, 0, 0, 0]
  cell_midpoints_rec:
    seq:
      - id: size
        type: u4
      - id: body
        type: cell_midpoints
        size: size - 4
  cell_midpoints:
    doc: |
      As `table_midpoints` (page coords) plus two trailing sub-records of
      Unknown semantics: a 19-byte record whose payload holds a u4 255, and a
      16-byte tail starting with u4 12.
    seq:
      - id: tag
        type: u2
        doc: Constant 6.
      - id: base
        type: u4
        doc: 91 at cell level.
      - id: one
        type: u2
      - id: flags
        type: u2
        doc: 0x0c01 at cell level.
      - id: point_count
        type: u4
      - id: points
        type: point
        repeat: expr
        repeat-expr: point_count
      - id: four
        type: u4
      - id: zeros5
        contents: [0, 0, 0, 0, 0]
      - id: rec19_size
        type: u4
        doc: Constant 19.
      - id: rec19_t5
        contents: [0x01, 0x00, 0x02, 0x00, 0x00]
      - id: rec19
        size: 14
        doc: Holds a u4 255 (Unknown).
      - id: tail16
        contents: [0x0c, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
  table_outline_rec:
    seq:
      - id: size
        type: u4
      - id: body
        type: table_outline
        size: size - 4
  table_outline:
    seq:
      - id: tag
        type: u2
        doc: Constant 7.
      - id: base
        type: u4
        doc: 0 at table level, 135 at cell level (Unknown semantics).
      - id: flags
        size: 7
      - id: four
        type: u4
      - id: pad_a
        size: 2
      - id: rect
        type: rect
        doc: (0,0,0,0) on the corpus.
      - id: pad_b
        size: 2
      - id: path
        type: path_rec
      - id: pad
        type: u1
  table_content:
    seq:
      - id: object_type
        type: u2
        doc: Constant 22 (the inline-object type).
      - id: const15
        type: u2
        doc: Constant 15.
      - id: pad
        type: u2
      - id: head
        size: 3
        doc: 01 04 02 on the corpus (Unknown).
      - id: content_u16
        type: u2
        doc: 7612 on the corpus (Unknown).
      - id: n_cols
        type: u4
      - id: col_widths
        type: f4
        repeat: expr
        repeat-expr: n_cols
      - id: n_rows
        type: u4
      - id: rows
        type: table_row
        repeat: expr
        repeat-expr: n_rows
      - id: tail_bbox
        type: rect
        doc: Page coordinates; equals the wrap bbox.
      - id: outer_borders
        type: border_block
        doc: The table's outer frame borders.
      - id: n_col_min
        type: u4
      - id: col_width_min
        type: f4
        repeat: expr
        repeat-expr: n_col_min
        doc: |
          Per-column width floor (291.2 = 1456/5 on the corpus — the app's
          5-column cap; Marker, values never varied).
      - id: n_col_max
        type: u4
      - id: col_width_max
        type: f4
        repeat: expr
        repeat-expr: n_col_max
        doc: Per-column width ceiling (1456.0 == max table width; Marker).
      - id: table_width_max
        type: f4
        doc: 1456.0 == note width minus the 2×72 page margins.
      - id: grid_borders
        type: border_block
        doc: The inner grid-line borders.
      - id: theme_fill_argb
        type: u4
        doc: |
          Theme default header/highlight fill (0xffeeebe7 beige on the corpus).
          Constant across styled variants — a theme value, not per-table state.
  table_row:
    doc: Chain record (size counts the bytes after the field).
    seq:
      - id: size
        type: u4
      - id: body
        type: table_row_body
        size: size
  table_row_body:
    seq:
      - id: preamble
        contents: [0, 0, 0, 0, 0x01, 0x00, 0x02, 0x00, 0x00]
      - id: height
        type: f4
      - id: row_index
        type: u4
      - id: n_cols
        type: u4
      - id: cells
        type: table_cell
        repeat: expr
        repeat-expr: n_cols
  table_cell:
    doc: Chain record.
    seq:
      - id: size
        type: u4
      - id: body
        type: table_cell_body
        size: size
  table_cell_body:
    seq:
      - id: zero
        type: u4
      - id: m0
        type: u1
        doc: Constant 1.
      - id: styled
        type: u1
        doc: |
          1 when the table carries any explicit styling (table-wide, not
          per-cell), else 0.
      - id: m2
        contents: [0x02, 0x00, 0x00]
      - id: col_index
        type: u4
      - id: one_a
        type: u4
      - id: one_b
        type: u4
      - id: fill_argb
        type: u4
        doc: |
          Explicit cell background fill as 0xAARRGGBB; 0 = no fill (theme
          default). The "evidenzia riga/colonna" header highlight leaves this
          0 and marks cells via a header-style span set instead.
      - id: bbox
        type: rect
        doc: Page coordinates (Y origin may be page-local or document-stacked).
      - id: b1
        type: u1
        doc: Constant 1.
      - id: inner_size
        type: u4
        doc: Bytes remaining in the cell body.
      - id: cwrap
        type: cell_wrap_rec
        doc: Cell wrap; same bbox, timestamp 0.
      - id: cmid
        type: cell_midpoints_rec
        doc: Cell edge midpoints (page coords).
      - id: coutline
        type: cell_outline
        doc: Cell outline path + the cell's nested Common frame.
      - id: terminator
        contents: [0x0f, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x02, 0x00, 0x00]
  cell_outline:
    doc: |
      Self-sized cell-level outline record: flags, a rect, the outline path,
      then the cell's Common frame and a 2-byte `00 02` trailer.
    seq:
      - id: size
        type: u4
      - id: body
        type: cell_outline_body
        size: size - 4
  cell_outline_body:
    seq:
      - id: tag
        type: u2
        doc: Constant 7.
      - id: base
        type: u4
        doc: 135 at cell level (Unknown semantics).
      - id: flags
        size: 7
      - id: four
        type: u4
      - id: pad_a
        size: 2
      - id: rect
        type: rect
        doc: (0,0,0,0) on the corpus.
      - id: pad_b
        size: 2
      - id: path
        type: path_rec
        doc: |
          The cell rect as a closed path (page coords). Its last point is the
          cell's bottom-left corner — the legacy scan's "anchor".
      - id: pad
        type: u1
      - id: frame_size
        type: u4
      - id: frame
        type: common_frame
        size: frame_size
        doc: The cell's rich-text `text_core::Common` frame.
      - id: trailer
        contents: [0x00, 0x02]
  path_rec:
    doc: |
      Chain-sized path record: u4 n_ops then opcodes 1 = moveto (f8 x, f8 y),
      2 = lineto (f8 x, f8 y), 6 = closepath (no point). Corpus paths are all
      closed rectangles.
    seq:
      - id: size
        type: u4
      - id: body
        type: path_body
        size: size
  path_body:
    seq:
      - id: n_ops
        type: u4
      - id: ops
        type: path_op
        repeat: expr
        repeat-expr: n_ops
  path_op:
    seq:
      - id: op
        type: u1
      - id: x
        type: f8
        if: op != 6
      - id: y
        type: f8
        if: op != 6
  common_frame:
    doc: |
      A `text_core::Common` rich-text frame (here: a table cell's). Same layout
      as the note's title/body frames: text, span vector, paragraph vector,
      margins, gravity, sections, inline objects.
    seq:
      - id: char_count
        type: u4
      - id: text_utf16
        size: char_count * 2
        doc: UTF-16LE text (kept raw; the validator decodes and compares).
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
        doc: 0 top, 1 centre, 2 bottom.
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
      - id: inline_object_count
        type: u4
        if: inline_present != 0
      - id: inline_objects
        type: inline_object
        repeat: expr
        repeat-expr: inline_object_count
        if: inline_present != 0
  span_rec:
    doc: |
      Character-style span with cell-local coordinates. Ground-truth-confirmed
      span types: 1 foreground_color (extra = LE 0xAARRGGBB), 3 font_size
      (extra = f4 pt), 5 bold / 6 italic / 7 underline / 20 strikethrough
      (extra = u4 bool). Payloads end with a constant zero u4.
    seq:
      - id: record_size
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
        size: record_size - 16
  paragraph_rec:
    seq:
      - id: record_size
        type: u2
      - id: paragraph_type
        type: u4
      - id: start
        type: u4
      - id: end
        type: u4
      - id: extra
        size: record_size - 12
  section_pair:
    seq:
      - id: a
        type: u4
      - id: b
        type: u4
  inline_object:
    doc: Opaque here; a nested table would recurse via this same spec.
    seq:
      - id: frame_size
        type: u4
      - id: blob
        size: frame_size
  border_block:
    doc: |
      Chain-sized block of 4 border entries. Entries 0/2 are the vertical
      edges/lines and 1/3 the horizontal ones (pair members never differed on
      the corpus, so left-vs-right / top-vs-bottom stay unresolved). A disabled
      border is fully zeroed. The radii are the rounded-corner radii (26.0 on
      the default outer frame, 0 on sharp "90°" frames and on grid lines).
    seq:
      - id: size
        type: u4
      - id: body
        type: border_block_body
        size: size
  border_block_body:
    seq:
      - id: zero
        type: u4
      - id: t5
        contents: [0x01, 0x00, 0x02, 0x00, 0x00]
      - id: entries
        type: border_entry
        repeat: expr
        repeat-expr: 4
  border_entry:
    doc: |
      One border edge: colour + stroke width + the two rounded-corner radii.
      Corpus values: colour `ffb1ac98` (the grey frame/grid line), width `1.0`,
      radius `26.0` on the default (rounded) outer frame and `0.0` on a sharp
      "90°" frame and on all grid lines. Disabled edges are fully zeroed.
    seq:
      - id: argb
        type: u4
        doc: 0xAARRGGBB; 00000000 = border disabled. ffb1ac98 on the corpus.
      - id: width
        type: f4
        doc: Stroke width; 1.0 corpus-wide (never varied).
      - id: radius_x
        type: f4
        doc: Rounded-corner radius X; 26.0 rounded frame, 0.0 sharp/grid.
      - id: radius_y
        type: f4
        doc: Rounded-corner radius Y; matches radius_x on the corpus.
  point:
    seq:
      - id: x
        type: f8
      - id: y
        type: f8
  rect:
    seq:
      - id: x0
        type: f8
      - id: y0
        type: f8
      - id: x1
        type: f8
      - id: y1
        type: f8
