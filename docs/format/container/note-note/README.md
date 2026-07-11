# `note.note`

The document's **content and metadata** member (everything that is not per-page
ink geometry): metadata header, the typed rich text (title + body), tables, pen
state, voice recordings, and the trailing hash.

- **Formal spec (whole member):** [`spec/ksy/sdocx_note.ksy`](../../../../spec/ksy/sdocx_note.ksy)
  (validated corpus-wide — see [validation](#validation)).
- **Reference parsers:** the structural parser `parse_note_doc` in
  [`pysdocx/note_doc.py`](../../../../pysdocx/note_doc.py) (sequential, exact
  boundaries), plus the render-oriented scans `parse_note_metadata`,
  `parse_typed_text`, `parse_tables`, `scan_note_tail_records` in
  [`pysdocx/note.py`](../../../../pysdocx/note.py).
- **CLI:** `.venv/bin/python -m pysdocx note-doc <file> [--json] [--spans]`.
- **Conventions:** [`../../00-conventions.md`](../../00-conventions.md).

## Shape of the file — Decoded (sequential)

The whole member is one sequential structure. Cross-referenced against
`squ1dd13/sdocx2pdf` (MIT) and re-validated field-by-field on the corpus; the
hard gate is positional: parsing every field in order must consume exactly
`note.note[:-32]`, whose SHA-256 is the trailing 32 bytes.

```
offset  size  field                 status    note
0       4     flex_offset           Decoded   absolute offset of the flex-field region
                                              (alias offset_to_data)
4       1+n   property_flags        Decoded   var bitfield [u8 n][n bytes]; alias `flags`;
                                              corpus 0x0/0x8; bit 3 confirmed
                                              "is_background_colour_inverted"
                                              (2026-07-11, dark-theme sample)
..      1+n   field_flags           Decoded   var bitfield; alias `meta_flags`; each set
                                              bit gates one flex field (see below)
..      4     format_version        Decoded   4000 / 5400 (= end_tag.bin)
..      2+2c  note_id               Decoded   u16 char_len + UTF-16LE (empty on corpus)
..      4     file_revision         Decoded
..      8     created_time_us       Decoded   epoch MICROseconds
..      8     modified_time_us      Decoded   epoch µs (= end_tag.bin modified)
..      4     width                 Decoded
..      4     height                Decoded   stacked note height (sum over pages)
..      4     page_h_padding        Decoded
..      4     page_v_padding        Decoded
..      4     min_format_version    Decoded
..      4     title_size            Decoded
..      var   title_blob            Partial   Text object; inner Common frame carries the
                                              title text (typed-text.md)
..      4     body_size             Decoded
..      var   body_blob             Partial   Text object; inner Common frame carries the
                                              body rich text + table cells (typed-text.md)
..      0/8   pre_flex_gap          Unknown   when 8 bytes: u32 pair
                                              (width, round(width*sqrt(2))) — default
                                              page-size candidate; 12/14 have it
..      var   flex fields           Decoded   one per set field_flags bit, in bit order
EOF-32  32    trailing_hash         Decoded   sha256(note.note[:-32]) = pageIdInfo head_hash
```

## `field_flags` (alias `meta_flags`) — Decoded

`meta_flags` is not an opaque flag word: it is the **field-flags bitfield** of
the flex region. Each set bit means one field is present after the gap, in bit
order:

| bit | mask | flex field | corpus |
|---|---|---|---|
| 0 | 0x1 | `app_name` (short-utf16) | 0/14 |
| 1 | 0x2 | `app_version` (u32 major, u32 minor, short-utf16 patch) | 0/14 |
| 2 | 0x4 | `author_info` (3× short-utf16, u32 image_id) | 0/14 |
| 3 | 0x8 | `latitude_longitude` (f64, f64) | 0/14 |
| 6 | 0x40 | `template_uri` (short-utf16) | 0/14 |
| 7 | 0x80 | `last_edited_page_index` (u32) | 14/14 |
| 9 | 0x200 | `last_edited_page_image_id` (i32) + `last_edited_page_time_us` (i64) | 14/14 |
| 10 | 0x400 | `string_registry` (u32 size; u16 count × [u32 id, short-utf16]) | 11/14 |
| 11 | 0x800 | `body_text_font_size_delta` (i32) | 14/14 |
| 12 | 0x1000 | `compatible_last_pen_info` (pen record, un-prefixed) | 0/14 |
| 13 | 0x2000 | `voice_data` (u32 count × voice recording) | 2/14 |
| 14 | 0x4000 | `attached_files` (u16 count × [short-utf16, u32 file_id]) | 0/14 |
| 15 | 0x8000 | `last_pen_info` (pen record, inclusive-length-prefixed) | 11/14 |
| 16 | 0x10000 | `server_check_point` (i64) | 0/14 |
| 17 | 0x20000 | `fixed_font` (short-utf16) | 0/14 |
| 18 | 0x40000 | `fixed_text_direction` (u32: 0 ltr, 1 rtl, 2 default) | 14/14 |
| 19 | 0x80000 | `fixed_background_theme` (u32: 0 light, 1 dark, 2 default) | 14/14 |
| 20 | 0x100000 | `text_summarisation` (short-utf16) | 0/14 |
| 21 | 0x200000 | `stroke_group_size` (u32) | 0/14 |
| 22 | 0x400000 | `app_custom_data` (long-utf16) | 0/14 |

Bits with corpus 0/14 are modeled from `sdocx2pdf` and parse structurally but
are not yet exercised by a sample (Marker, not corpus-proven).

**Correction:** this page previously promoted `0x2000` as *has-tables*. The two
notes that set it also happen to be the only two with tables, but structurally
bit 13 gates **voice_data** — both notes carry a voice recording, and tables
live inside the body text's inline objects instead
([typed-text](./typed-text.md)). The former `0x400`/`0x8000` Unknowns are
`string_registry`/`last_pen_info`.

The old "tail records" nomenclature (tail sentinel, pen preload paths, preload
parameter hints, pen style tails, voice clip records, tail hash block) maps
onto these flex fields one-for-one — see [tail-records](./tail-records.md).

## Trailing hash — Decoded

The last 32 bytes of `note.note` are the SHA-256 digest of every preceding
byte: `note.note[-32:] == sha256(note.note[:-32])` (14/14).
`pageIdInfo.dat.head_hash` is a copy of this digest. Because the digest sits
immediately after the last flex field, "the sequential parse lands exactly on
the hash" is the corpus-wide proof of every intermediate boundary.

## Validation

```bash
.venv/bin/python spec/tools/validate_note.py
# -> 14 matched, 0 mismatched, out of 14 parsed
.venv/bin/python spec/tools/analyze_note_doc.py
# -> parse/landed-on-hash/title/body/span/cell/voice cross-checks, all clean
```

`validate_note.py` compares every modeled field — header, bitfields, blob
boundaries, the pre-flex gap, all flex fields (string registry, pen records,
voice recordings, attached files, …) and the trailing hash — between the
Kaitai parse and `pysdocx.note_doc.parse_note_doc` / `parse_note_metadata`.
`analyze_note_doc.py` additionally cross-checks the structural parse against
the independent marker scans (typed text, style runs, tables, voice, pens).
Toolchain: [`../../../../spec/README.md`](../../../../spec/README.md).
