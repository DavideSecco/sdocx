meta:
  id: sdocx_end_tag
  title: Samsung Notes .sdocx end_tag.bin footer record
  application: Samsung Notes / S Pen SDK
  file-extension: bin
  endian: le
  license: CC0-1.0
doc: |
  The `end_tag.bin` member of a Samsung Notes `.sdocx` archive: a sequential
  S Pen SDK document footer. The field names are independently cross-checked
  against `sdocx2pdf` and validated on the 13-sample corpus. Two size families
  are seen: a 148-byte footer (payload_size = 146) on newer notes, and a
  144-byte footer (payload_size = 142) on `handwritten.sdocx`; the shorter
  legacy footer omits the zero-length `app_custom_data` field before the
  signature.
seq:
  - id: payload_size
    type: u2
    doc: Byte count following this field; equals (file size - 2).
  - id: format_version
    type: u4
    doc: Format version; matches note.note format_version (13/13).
  - id: note_uuid_len
    type: u2
  - id: note_uuid
    type: str
    size: note_uuid_len * 2
    encoding: UTF-16LE
    doc: SDK note UUID string; empty on the current corpus.
  - id: modified_time
    type: s8
    doc: Note modified timestamp; matches note.note modified_time (13/13).
  - id: property_flags
    type: u4
    doc: SDK property flags; bit 1 is `is_landscape` in sdocx2pdf. Zero on the corpus.
  - id: cover_image_len
    type: u2
  - id: cover_image
    type: str
    size: cover_image_len * 2
    encoding: UTF-16LE
    doc: Cover image identifier; empty on the current corpus.
  - id: note_width
    type: u4
    doc: Document/page width.
  - id: document_height
    type: f4
    doc: Document/note height; equals note.note height on the current corpus.
  - id: app_name_len
    type: u2
  - id: app_name
    type: str
    size: app_name_len * 2
    encoding: UTF-16LE
    doc: App name; empty on the current corpus.
  - id: app_version_major
    type: u4
  - id: app_version_minor
    type: u4
  - id: app_version_patch_name_len
    type: u2
  - id: app_version_patch_name
    type: str
    size: app_version_patch_name_len * 2
    encoding: UTF-16LE
  - id: min_format_version
    type: u4
    doc: Minimum format version; equal to format_version on the current corpus.
  - id: created_time_header
    type: s8
    doc: Creation time; matches note.note created_time (13/13).
  - id: last_viewed_page_index
    type: u4
  - id: page_model
    type: u2
    doc: 0 = paged/list, 1 = pageless/single in sdocx2pdf.
  - id: document_type
    type: u2
    doc: 0 = unlocked document on the current corpus.
  - id: owner_id_len
    type: u2
  - id: owner_id
    type: str
    size: owner_id_len * 2
    encoding: UTF-16LE
  - id: skipped_size
    type: u4
  - id: skipped_data
    size: skipped_size
  - id: encryption_data_size
    type: u4
  - id: encryption_data
    size: encryption_data_size
  - id: display_created_time
    type: s8
  - id: display_modified_time
    type: s8
  - id: last_recognised_data_modified_time
    type: s8
  - id: fixed_font_len
    type: u2
  - id: fixed_font
    type: str
    size: fixed_font_len * 2
    encoding: UTF-16LE
  - id: fixed_text_direction
    type: u4
    doc: 2 = default on the current corpus.
  - id: fixed_background_theme
    type: u4
    doc: 2 = default on the current corpus.
  - id: server_checkpoint
    type: s8
    doc: -1 on the current corpus.
  - id: new_orientation
    type: u4
    doc: 0 = portrait on the current corpus.
  - id: min_unknown_version
    type: u4
  - id: app_custom_data_len
    type: u4
    if: _io.pos < _io.size - 22
  - id: app_custom_data
    type: str
    size: app_custom_data_len * 2
    encoding: UTF-16LE
    if: _io.pos < _io.size - 22
instances:
  page_width:
    pos: 22
    type: u2
    doc: Low 16 bits of note_width; equals the page header width on the current corpus.
  format_version_dup:
    pos: 42
    type: u4
    doc: Back-compat alias for min_format_version.
  created_time_a:
    pos: 72
    type: s8
    doc: Back-compat alias for display_created_time.
  created_time_b:
    pos: 80
    type: s8
    doc: Back-compat alias for display_modified_time.
  extra_time_candidate:
    pos: 88
    type: s8
    doc: Back-compat alias for last_recognised_data_modified_time.
  signature:
    pos: _io.size - 22
    size: 22
    type: str
    encoding: ASCII
    doc: Trailing ASCII marker; always "Document for S-Pen SDK".
