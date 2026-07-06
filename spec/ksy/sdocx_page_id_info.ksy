meta:
  id: sdocx_page_id_info
  title: Samsung Notes .sdocx pageIdInfo.dat page-order manifest
  application: Samsung Notes / S Pen SDK
  file-extension: dat
  endian: le
  license: CC0-1.0
doc: |
  The `pageIdInfo.dat` member of a `.sdocx` archive. It defines the true page
  order of the document (the `.page` members are named by UUID, not by order)
  and carries an opaque per-page hash.

  Layout is fully decoded with zero counterexamples across the 13-sample corpus:
  a 32-byte document head hash, a `u16` page count, then that many fixed 106-byte
  records. Every record is a 36-char UTF-16LE page UUID followed by a 32-byte
  per-page hash; the record is exactly filled (2 + 72 + 32 = 106), so there is no
  trailing padding.

  The per-page hash is stable manifest data but is NOT the SHA-256 of the raw
  `.page` member (0/48 matches on the corpus); its construction is Unknown and is
  documented as such in the companion Markdown rather than named here.
seq:
  - id: head_hash
    size: 32
    doc: 32-byte document-level head hash. Semantics Unknown; stable per file.
  - id: page_count
    type: u2
    doc: Number of page records that follow.
  - id: pages
    type: page_record
    repeat: expr
    repeat-expr: page_count
    doc: Page order — index in this list is the document page order.
types:
  page_record:
    seq:
      - id: uuid_len
        type: u2
        doc: UTF-16 character count of the UUID; always 36 on the corpus.
      - id: uuid
        type: str
        size: uuid_len * 2
        encoding: UTF-16LE
        doc: Page UUID; matches a `<uuid>.page` archive member.
      - id: page_hash
        size: 32
        doc: Opaque per-page hash (not SHA-256 of the .page member).
