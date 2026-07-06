meta:
  id: sdocx_media_info
  title: Samsung Notes .sdocx media/mediaInfo.dat manifest
  application: Samsung Notes / S Pen SDK
  file-extension: dat
  endian: le
  license: CC0-1.0
doc: |
  The `media/mediaInfo.dat` manifest inside a `.sdocx` archive: one record per
  attachment under `media/`, closed by the ASCII trailer `EOFX`.

  Fully decoded with zero counterexamples across the 13-sample corpus: a `u32`
  magic, a `u16` record count, then that many length-prefixed records. Each
  record's `payload_size` counts the bytes after itself and frames a body of
  `[u32 media_index][u16 name_chars][UTF-16LE filename][64-byte ASCII SHA-256
  hex][raw tail]`. The filename already includes the `<index>@...` prefix used
  under `media/`. On the corpus, 60/60 records point at existing archive members
  and every SHA-256 verifies.

  The record's 11-byte tail is structurally modeled as
  `[u16 tag][u64 time_candidate][u8 marker]`. The boundaries are decoded with
  zero counterexamples; the tag/time semantics remain deliberately conservative
  (see the companion Markdown).
seq:
  - id: magic
    type: u4
    doc: Manifest magic. Corpus values 0x1518 (x12) and 0x1452 (x1).
  - id: record_count
    type: u2
    doc: Number of media records that follow.
  - id: records
    type: media_record
    repeat: expr
    repeat-expr: record_count
  - id: eof
    type: str
    size: 4
    encoding: ASCII
    doc: Always the ASCII trailer "EOFX".
types:
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
          Trailing 11-byte record tail. Structurally decoded; tag/time
          semantics remain Unknown.
  media_tail:
    seq:
      - id: tag
        type: u2
        doc: Corpus values 1, 3, 5, 20; exact semantics Unknown.
      - id: time_candidate
        type: u8
        doc: Timestamp-like value near note/media edit times; exact semantics Unknown.
      - id: marker
        type: u1
        doc: Constant 1 on 60/60 corpus records.
