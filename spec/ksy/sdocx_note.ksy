meta:
  id: sdocx_note
  title: Samsung Notes .sdocx note.note sequential note-doc structure
  application: Samsung Notes / S Pen SDK
  file-extension: note
  endian: le
  license: CC0-1.0
  imports:
    - sdocx_text_wrapper
doc: |
  The whole `note.note` member of a `.sdocx` archive, parsed as one sequential
  structure (validated with zero counterexamples across the corpus by
  `spec/tools/validate_note.py` and `spec/tools/analyze_note_doc.py`).

  Layout: a fixed header (two variable-length bitfields, ids, timestamps in
  epoch MICROseconds, note geometry), the length-prefixed title and body Text
  blobs, an optional pre-flex gap, then a run of optional "flex" fields, each
  gated by one bit of `field_flags`, and finally the trailing 32-byte
  `sha256(note.note[:-32])` digest (the same digest copied into
  `pageIdInfo.dat.head_hash`). The parse consuming bytes `0 .. size-32`
  exactly is the structural gate: every intermediate boundary must be correct
  for `trailing_hash` to land on the real hash.

  The title/body blobs are Text objects parsed through the imported
  `sdocx_text_wrapper` inheritance chain; Shape's flex offset lands on their
  `text_core::Common` rich-text frame without scanning (see
  docs/format/container/note-note/typed-text.md). Everything else that was
  previously marker-scanned in the tail (pen preload paths, pen style tails,
  voice clips, the string registry pairing each pen with its parameter
  string) is now these flex fields.

  Field names cross-referenced from squ1dd13/sdocx2pdf (MIT), re-validated
  field-by-field on the local corpus. Old pysdocx aliases: `flex_offset` was
  `offset_to_data`, `property_flags` was `flags`, `field_flags` was
  `meta_flags`.
seq:
  - id: flex_offset
    type: u4
    doc: |
      Absolute offset where the flex-field region begins (alias
      offset_to_data). The gap between the end of the body blob and this
      offset is `pre_flex_gap` (0 or 8 bytes on the corpus).
  - id: property_flags
    type: var_bitfield
    doc: |
      Variable-length property bitfield (alias `flags`). Corpus values 0x0 and
      0x8; sdocx2pdf reads bit 3 as `is_background_colour_inverted` (semantic
      untested here — Marker).
  - id: field_flags
    type: var_bitfield
    doc: |
      Variable-length field bitfield (alias `meta_flags`): each set bit gates
      one optional flex field after the pre-flex gap, in bit order. Observed
      on the corpus: bits 7, 9, 10, 11, 13, 15, 18, 19. Bits 0-3, 6, 12, 14,
      16, 17, 20-22 are modeled from sdocx2pdf but not yet exercised by a
      corpus sample.
  - id: format_version
    type: u4
    doc: Format version. Corpus values 4000 and 5400; matches end_tag.bin.
  - id: note_id
    type: short_utf16
    doc: Note UUID string (length-prefixed UTF-16LE; empty on the corpus).
  - id: file_revision
    type: u4
    doc: Monotonic-ish document revision counter.
  - id: created_time_us
    type: s8
    doc: Creation time, epoch microseconds.
  - id: modified_time_us
    type: s8
    doc: Modified time, epoch microseconds; matches end_tag.bin modified_time.
  - id: width
    type: u4
    doc: Note width.
  - id: height
    type: u4
    doc: Stacked note height (sum over pages), not a per-page height.
  - id: page_h_padding
    type: u4
    doc: Horizontal page padding.
  - id: page_v_padding
    type: u4
    doc: Vertical page padding.
  - id: min_format_version
    type: u4
    doc: Minimum reader format version.
  - id: title_size
    type: u4
    doc: Byte length of the title Text blob that follows.
  - id: title_blob
    type: sdocx_text_wrapper
    size: title_size
    doc: |
      Title Text object. Its Shape flex region contains one
      `text_core::Common` frame carrying the title text.
  - id: body_size
    type: u4
    doc: Byte length of the body Text blob that follows.
  - id: body_blob
    type: sdocx_text_wrapper
    size: body_size
    doc: |
      Body Text object blob. Contains the main `text_core::Common` rich-text
      frame (typed text, spans, paragraphs, margins, gravity, sections,
      inline objects) plus one nested Common frame per table cell.
  - id: pre_flex_gap
    size: flex_offset - _io.pos
    type: pre_flex_gap
    doc: |
      Gap between the body blob and `flex_offset`: 0 or 8 bytes on the corpus.
      sdocx2pdf skips it as an unexplained underread; when 8 bytes it holds a
      u32 pair `(width, round(width*sqrt(2)))` — an A4-proportioned
      default-page-size candidate. Semantics Unknown.
  - id: app_name
    type: short_utf16
    if: has_app_name
  - id: app_version
    type: app_version
    if: has_app_version
  - id: author_info
    type: author_info
    if: has_author_info
  - id: latitude_longitude
    type: geo_position
    if: has_latitude_longitude
  - id: template_uri
    type: short_utf16
    if: has_template_uri
  - id: last_edited_page_index
    type: u4
    if: has_last_edited_page
  - id: last_edited_page_image_id
    type: s4
    if: has_last_edited_page_image_and_time
  - id: last_edited_page_time_us
    type: s8
    if: has_last_edited_page_image_and_time
  - id: string_registry
    type: string_registry
    if: has_string_registry
    doc: |
      Registered strings referenced by id elsewhere. On the corpus this pairs
      each pen preload resource name with its advanced-settings parameter
      string (e.g. "8;", "18;0;100;") — previously the marker-scanned
      pen_preload_path / parameter-hint tail records.
  - id: body_text_font_size_delta
    type: s4
    if: has_body_text_font_size_delta
  - id: compatible_last_pen_info
    type: pen_info_simple
    if: has_compatible_last_pen_info
  - id: voice_data
    type: voice_data
    if: has_voice_data
    doc: |
      Voice recordings (previously the marker-scanned voice_clip records).
      `field_flags` bit 13 (0x2000) gates this — NOT "has-tables" as this
      repo previously hypothesized; tables live in the body text's inline
      objects instead.
  - id: attached_files
    type: attached_files
    if: has_attached_files
  - id: last_pen_info
    type: pen_info_full
    if: has_last_pen_info
  - id: server_check_point
    type: s8
    if: has_server_check_point
  - id: fixed_font
    type: short_utf16
    if: has_fixed_font
  - id: fixed_text_direction
    type: u4
    if: has_fixed_text_direction
    doc: 0 ltr, 1 rtl, 2 default (sdocx2pdf names; corpus value 2).
  - id: fixed_background_theme
    type: u4
    if: has_fixed_background_theme
    doc: 0 light, 1 dark, 2 default (sdocx2pdf names; corpus value 2).
  - id: text_summarisation
    type: short_utf16
    if: has_text_summarisation
  - id: stroke_group_size
    type: u4
    if: has_stroke_group_size
  - id: app_custom_data
    type: long_utf16
    if: has_app_custom_data
  - id: trailing_hash
    size: 32
    doc: |
      `sha256(note.note[:-32])`; exactly pageIdInfo.dat `head_hash`. Reaching
      it with 32 bytes left is the structural gate for the whole sequence.
instances:
  has_app_name:
    value: (field_flags.value >> 0) & 1 != 0
  has_app_version:
    value: (field_flags.value >> 1) & 1 != 0
  has_author_info:
    value: (field_flags.value >> 2) & 1 != 0
  has_latitude_longitude:
    value: (field_flags.value >> 3) & 1 != 0
  has_template_uri:
    value: (field_flags.value >> 6) & 1 != 0
  has_last_edited_page:
    value: (field_flags.value >> 7) & 1 != 0
  has_last_edited_page_image_and_time:
    value: (field_flags.value >> 9) & 1 != 0
  has_string_registry:
    value: (field_flags.value >> 10) & 1 != 0
  has_body_text_font_size_delta:
    value: (field_flags.value >> 11) & 1 != 0
  has_compatible_last_pen_info:
    value: (field_flags.value >> 12) & 1 != 0
  has_voice_data:
    value: (field_flags.value >> 13) & 1 != 0
  has_attached_files:
    value: (field_flags.value >> 14) & 1 != 0
  has_last_pen_info:
    value: (field_flags.value >> 15) & 1 != 0
  has_server_check_point:
    value: (field_flags.value >> 16) & 1 != 0
  has_fixed_font:
    value: (field_flags.value >> 17) & 1 != 0
  has_fixed_text_direction:
    value: (field_flags.value >> 18) & 1 != 0
  has_fixed_background_theme:
    value: (field_flags.value >> 19) & 1 != 0
  has_text_summarisation:
    value: (field_flags.value >> 20) & 1 != 0
  has_stroke_group_size:
    value: (field_flags.value >> 21) & 1 != 0
  has_app_custom_data:
    value: (field_flags.value >> 22) & 1 != 0
  has_unhandled_field_bits:
    value: field_flags.value & 0xff800130 != 0
    doc: |
      True if any field bit outside the modeled set (0-3, 6, 7, 9-22) is set;
      the sequence after the gap would then be misaligned. Zero on the corpus.
types:
  var_bitfield:
    doc: |
      `[u8 n_bytes][n-byte little-endian bitfield]`, n <= 4. On the corpus n
      is always 4.
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
  long_utf16:
    doc: A u32 character count followed by that many UTF-16LE code units.
    seq:
      - id: char_len
        type: u4
      - id: value
        type: str
        size: char_len * 2
        encoding: UTF-16LE
  pre_flex_gap:
    seq:
      - id: maybe_default_page_size
        type: u4
        repeat: expr
        repeat-expr: 2
        if: _io.size == 8
        doc: |
          Observed `(width, round(width*sqrt(2)))` on every 8-byte gap in the
          corpus. Semantics Unknown (default page size candidate).
      - id: rest
        size-eos: true
  app_version:
    seq:
      - id: major
        type: u4
      - id: minor
        type: u4
      - id: patch_name
        type: short_utf16
  author_info:
    seq:
      - id: strings
        type: short_utf16
        repeat: expr
        repeat-expr: 3
      - id: image_id
        type: u4
  geo_position:
    seq:
      - id: latitude
        type: f8
      - id: longitude
        type: f8
  string_registry:
    seq:
      - id: byte_size
        type: u4
      - id: body
        type: string_registry_body
        size: byte_size
        if: byte_size > 0
  string_registry_body:
    seq:
      - id: count
        type: u2
      - id: entries
        type: string_registry_entry
        repeat: expr
        repeat-expr: count
  string_registry_entry:
    seq:
      - id: string_id
        type: u4
      - id: value
        type: short_utf16
  pen_info_simple:
    doc: Un-prefixed pen record (field bit 12, compatible_last_pen_info).
    seq:
      - id: name
        type: short_utf16
      - id: pen_size
        type: f4
      - id: color
        size: 4
      - id: is_curvable
        type: u4
      - id: advanced_settings
        type: short_utf16
      - id: is_eraser_enabled
        type: u4
      - id: size_level
        type: u4
      - id: particle_density
        type: u4
      - id: ui_color_hsv
        type: f4
        repeat: expr
        repeat-expr: 3
      - id: ui_color_info
        type: u4
  pen_info_full:
    doc: Inclusive-length-prefixed pen record (field bit 15, last_pen_info).
    seq:
      - id: total_size
        type: u4
      - id: body
        type: pen_info_full_body
        size: total_size - 4
  pen_info_full_body:
    seq:
      - id: name
        type: short_utf16
      - id: pen_size
        type: f4
      - id: color
        size: 4
      - id: is_curvable
        type: u4
      - id: advanced_settings
        type: short_utf16
      - id: is_eraser_enabled
        type: u4
      - id: size_level
        type: u4
      - id: particle_density
        type: u4
      - id: particle_size
        type: f4
      - id: is_fixed_width
        type: u4
      - id: ui_color_hsv
        type: f4
        repeat: expr
        repeat-expr: 3
      - id: ui_color_info
        type: u4
      - id: is_fixed_opacity
        type: u4
        if: _io.size - _io.pos >= 4
        doc: Late-addition trailing field; present only when bytes remain.
      - id: is_auto_size_enabled
        type: u4
        if: _io.size - _io.pos >= 4
      - id: fit_ratio
        type: f4
        if: _io.size - _io.pos >= 4
  voice_data:
    seq:
      - id: count
        type: u4
      - id: recordings
        type: voice_recording
        repeat: expr
        repeat-expr: count
  voice_recording:
    seq:
      - id: total_size
        type: u4
      - id: body
        type: voice_recording_body
        size: total_size
  voice_recording_body:
    seq:
      - id: file_id
        type: u4
        doc: mediaInfo.dat media index of the .m4a recording.
      - id: name
        type: short_utf16
      - id: duration_str
        type: short_utf16
      - id: created_time_ms
        type: s8
        doc: >
          Epoch MILLIseconds — not micros, unlike `voice_event.time_us` below and
          every other `_us` timestamp in this format. Verified on the 2/2 corpus
          samples carrying voice clips: the raw value is 13 digits and only
          resolves to a sane date when treated as epoch millis.
      - id: event_count
        type: u4
      - id: events
        type: voice_event
        repeat: expr
        repeat-expr: event_count
      - id: precise_duration_ms
        type: s8
  voice_event:
    seq:
      - id: action
        type: u4
        doc: 0 none, 1 start, 2 pause, 3 resume, 4 stop (sdocx2pdf names).
      - id: time_us
        type: s8
  attached_files:
    seq:
      - id: count
        type: u2
      - id: entries
        type: attached_file
        repeat: expr
        repeat-expr: count
  attached_file:
    seq:
      - id: name
        type: short_utf16
      - id: file_id
        type: u4
        doc: mediaInfo.dat media index.
