meta:
  id: sdocx_media_info
  title: Samsung Notes .sdocx media/mediaInfo.dat manifest
  application: Samsung Notes / S Pen SDK
  file-extension: dat
  endian: le
  license: CC0-1.0
doc: |
  The `media/mediaInfo.dat` manifest inside a `.sdocx` archive: one record per
  attachment under `media/`, optionally followed by a length-framed shared-note
  extension, and closed by the ASCII trailer `EOFX`.

  Fully decoded with zero counterexamples across the 13-sample corpus: a `u32`
  format version, a `u16` record count, then that many length-prefixed records. Each
  record's `payload_size` counts the bytes after itself and frames a body of
  `[u32 media_index][u16 name_chars][UTF-16LE filename][64-byte ASCII SHA-256
  hex][raw tail]`. The filename already includes the `<index>@...` prefix used
  under `media/`. On the corpus, 60/60 records point at existing archive members
  and every SHA-256 verifies.

  The record's 11-byte tail is structurally modeled as
  `[u16 ref_count][u64 modified_time][u8 is_attached]`. The names are
  independently cross-checked against `sdocx2pdf`; the boundaries are decoded
  with zero counterexamples.
seq:
  - id: format_version
    type: u4
    doc: Manifest format version. Corpus values 5400 (x12) and 5202 (x1).
  - id: record_count
    type: u2
    doc: Number of media records that follow.
  - id: records
    type: media_record
    repeat: expr
    repeat-expr: record_count
  - id: content_file_data_list
    type: content_file_data_list
    if: _io.size - _io.pos > 4
    doc: Optional collaboration/COEDIT extension before EOFX.
  - id: eof
    type: str
    size: 4
    encoding: ASCII
    doc: Always the ASCII trailer "EOFX".
types:
  content_file_data_list:
    seq:
      - id: marker
        contents: [0x51, 0x30, 0x39, 0x4f, 0x56, 0x45, 0x56, 0x4f, 0x56, 0x46, 0x39, 0x47, 0x53, 0x55, 0x78, 0x46, 0x58, 0x30, 0x52, 0x42, 0x56, 0x45, 0x46, 0x66, 0x54, 0x45, 0x6c, 0x54, 0x56, 0x41]
        doc: Unpadded base64 for "CONTENT_FILE_DATA_LIST".
      - id: record_count
        type: u4
      - id: records
        type: content_file_record
        repeat: expr
        repeat-expr: record_count
  content_file_record:
    seq:
      - id: payload_size
        type: u4
      - id: body
        size: payload_size
        doc: Length-framed COEDIT metadata; inner semantics remain unknown.
  media_record:
    seq:
      - id: payload_size
        type: u4
        doc: Byte count of the body that follows (excludes this field).
      - id: body
        type: media_body
        size: payload_size
  media_body:
    seq:
      - id: media_index
        type: u4
        doc: Attachment index; matches the "<index>@" filename prefix.
      - id: name_len
        type: u2
        doc: UTF-16 character count of the filename.
      - id: name
        type: str
        size: name_len * 2
        encoding: UTF-16LE
        doc: Archive-relative filename under media/, including "<index>@" prefix.
      - id: sha256
        type: str
        size: 64
        encoding: ASCII
        doc: Lowercase hex SHA-256 of media/<name>. Verifies 60/60 on the corpus.
      - id: tail
        type: media_tail
        size-eos: true
        doc: |
          Trailing 11-byte record tail.
  media_tail:
    seq:
      - id: ref_count
        type: u2
        doc: Reference count candidate. Corpus values 1, 3, 5, 20.
      - id: modified_time
        type: u8
        doc: Media modified-time candidate, epoch milliseconds.
      - id: is_attached
        type: u1
        doc: Boolean attached flag. Constant 1 on 60/60 corpus records.
