meta:
  id: sdocx_note
  title: Samsung Notes .sdocx note.note top-level metadata header
  application: Samsung Notes / S Pen SDK
  file-extension: note
  endian: le
  license: CC0-1.0
doc: |
  The leading metadata header of a `.sdocx` archive's `note.note` member. This
  header is deterministic and fully decoded (zero counterexamples across the
  13-sample corpus). It ends at the title object blob; most content after it —
  typed rich text, tables, and marker-located tail records — is decoded
  procedurally (marker/TLV scanning, not a fixed layout) and is documented in
  the companion Markdown rather than forced into Kaitai:

    - typed rich text  -> docs/format/container/note-note/typed-text.md
    - tables           -> docs/format/container/note-note/tables.md
    - tail records     -> docs/format/container/note-note/tail-records.md

  Only fixed-boundary tail anchors are modeled as instances: the sentinel at
  `offset_to_data`, the trailing 32-byte note hash copied into pageIdInfo.dat,
  and the two EOF-relative tail-hash-block candidate windows seen in the corpus
  (EOF-aligned, or followed by a 4-byte post-hash u32). Marker-scanned pen and
  voice records remain procedural.

  Note the two single-byte pads after `offset_to_data` and after `flags`; they
  are part of the on-disk layout, not alignment we add.
seq:
  - id: offset_to_data
    type: s4
    doc: Absolute offset where the tail/body region (tail_sentinel) begins.
  - id: reserved_at_4
    size: 1
    doc: Single pad byte.
  - id: flags
    type: s4
    doc: Note flags. Corpus values 0x0 and 0x8.
  - id: reserved_at_9
    size: 1
    doc: Single pad byte.
  - id: meta_flags
    type: s4
    doc: |
      Note metadata flags. Bit 0x2000 = has-tables (set on exactly the 2
      table-bearing notes; agrees with independently parsed table cells). Other
      bits are base/constant or Unknown — see the docs.
  - id: format_version
    type: s4
    doc: Format version. Corpus values 4000 and 5400; matches end_tag.bin.
  - id: note_id
    type: short_utf16
    doc: Note UUID string (length-prefixed UTF-16LE).
  - id: file_revision
    type: s4
    doc: Monotonic-ish document revision counter.
  - id: created_time
    type: s8
    doc: Creation time (epoch ms).
  - id: modified_time
    type: s8
    doc: Modified time (epoch ms); matches end_tag.bin modified_time.
  - id: width
    type: s4
    doc: Page width.
  - id: height
    type: s4
    doc: Page height.
  - id: page_h_padding
    type: s4
    doc: Horizontal page padding.
  - id: page_v_padding
    type: s4
    doc: Vertical page padding.
  - id: min_format_version
    type: s4
    doc: Minimum reader format version.
  - id: title_size
    type: s4
    doc: |
      Byte length of the title object blob that follows. The blob's inner schema
      is only partially understood (the title text is scanned from it); it is
      not modeled here beyond its size.
  - id: title_blob
    size: 'title_size > 0 ? title_size : 0'
    doc: Title object blob (opaque here; see note-note docs).
instances:
  tail_sentinel:
    pos: offset_to_data
    size: 16
    doc: Fixed 16-byte tail sentinel at `offset_to_data`.
  trailing_hash:
    pos: _io.size - 32
    size: 32
    doc: The note's trailing hash; exactly pageIdInfo.dat `head_hash`.
  tail_hash_block_eof:
    pos: _io.size - 40
    type: tail_hash_block
    if: _io.size >= 40
    doc: Candidate 40-byte tail hash block when the block ends at EOF.
  tail_hash_block_before_post_u32:
    pos: _io.size - 44
    type: tail_hash_block
    if: _io.size >= 44
    doc: Candidate 40-byte tail hash block when followed by a 4-byte post-hash u32.
types:
  tail_hash_block:
    seq:
      - id: prefix_u32
        type: u4
        repeat: expr
        repeat-expr: 2
      - id: hash32
        size: 32
  short_utf16:
    doc: A u16 character count followed by that many UTF-16LE code units.
    seq:
      - id: char_len
        type: s2
      - id: value
        type: str
        size: 'char_len > 0 ? char_len * 2 : 0'
        encoding: UTF-16LE
