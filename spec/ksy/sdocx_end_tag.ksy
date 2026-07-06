meta:
  id: sdocx_end_tag
  title: Samsung Notes .sdocx end_tag.bin footer record
  application: Samsung Notes / S Pen SDK
  file-extension: bin
  endian: le
  license: CC0-1.0
doc: |
  The `end_tag.bin` member of a Samsung Notes `.sdocx` archive: a fixed-shape
  footer record that closes the document. Two size families are seen in the
  corpus: a 148-byte footer (payload_size = 146) on newer notes, and a
  144-byte footer (payload_size = 142) on `handwritten.sdocx`.

  Only the byte ranges named below are decoded with zero counterexamples across
  the 13-sample corpus. The gaps between them (documented as `*_raw` islands in
  the companion Markdown) are structurally bounded but not yet semantically
  named, so they are deliberately left unmodeled here rather than given
  speculative field names. The trailing footer constants and the ASCII
  signature are located from the end of the stream so both size families parse
  with one definition.
seq:
  - id: payload_size
    type: u2
    doc: Byte count following this field; equals (file size - 2).
  - id: format_version
    type: u2
    doc: Format version; matches note.note format_version (13/13).
  - id: reserved_at_4
    type: u4
    doc: Always zero on the current corpus.
  - id: modified_time
    type: s8
    doc: Note modified time (epoch ms); matches note.note modified_time (13/13).
instances:
  page_width:
    pos: 22
    type: u2
    doc: Page width; equals the page header width on the current corpus.
  document_height:
    pos: 26
    type: f4
    doc: Document/note height; equals note.note height on the current corpus.
  format_version_dup:
    pos: 42
    type: u2
    doc: Duplicate of format_version; equal to it on every sample.
  created_time_header:
    pos: 46
    type: s8
    doc: Creation-time candidate carried in the header region.
  created_time_a:
    pos: 72
    type: s8
    doc: |
      Creation-time candidate. Exact note created_time on the 10 newer samples;
      a millisecond-close value on the 3 older imported samples.
  created_time_b:
    pos: 80
    type: s8
    doc: |
      Second creation-time candidate; identical to created_time_a on the 10
      newer samples, a different ms-like time on the older imports.
  extra_time_candidate:
    pos: 88
    type: s8
    doc: Additional timestamp-like value; non-zero on only 2 samples.
  signature:
    pos: _io.size - 22
    size: 22
    type: str
    encoding: ASCII
    doc: Trailing ASCII marker; always "Document for S-Pen SDK".
