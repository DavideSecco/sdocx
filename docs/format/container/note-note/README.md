# `note.note`

The document's **content and metadata** member (everything that is not per-page
ink geometry): the top-level metadata header, the typed rich text, tables, and a
tail region of records.

- **Formal spec (header only):** [`spec/ksy/sdocx_note.ksy`](../../../../spec/ksy/sdocx_note.ksy)
  (validated corpus-wide — see [validation](#validation)).
- **Reference parser:** `parse_note_metadata`, `parse_typed_text`, `parse_tables`,
  `scan_note_tail_records` in [`pysdocx/note.py`](../../../../pysdocx/note.py).
- **Conventions:** [`../../00-conventions.md`](../../00-conventions.md).

## Shape of the file

`note.note` has one deterministic part and three procedural parts:

| Region | Nature | Where |
|---|---|---|
| Top-level metadata header | **Decoded**, fixed layout | this page (below) |
| Typed rich text | Marker / TLV scan | [`typed-text.md`](./typed-text.md) |
| Tables | Marker / inferred | [`tables.md`](./tables.md) |
| Tail records (from `offset_to_data`) | Marker scan | [`tail-records.md`](./tail-records.md) |

Only the header is a fixed byte layout, so only the header is in the `.ksy`. The
other three are located by content markers and length-prefixed records, not by
fixed offsets, so they are documented as algorithms and left to the reference
parser. This is a deliberate line (see [conventions](../../00-conventions.md)):
a `.ksy` states positions we can prove; procedural decoding stays in prose.

## Top-level metadata header — Decoded

Little-endian. Note the two single-byte pads (part of the layout, not our
alignment). Holds across all 13 corpus samples with zero counterexamples.

```
offset  size  field               status    note
0       4     offset_to_data      Decoded   start of the tail region
4       1     reserved_at_4       Decoded   pad
5       4     flags               Decoded   0x0 / 0x8
9       1     reserved_at_9       Decoded   pad
10      4     meta_flags          Decoded   bit 0x2000 = has-tables
14      4     format_version      Decoded   4000 / 5400 (= end_tag.bin)
18      2+n   note_id             Decoded   s16 char_len + UTF-16LE
...     4     file_revision       Decoded
...     8     created_time        Decoded   epoch ms
...     8     modified_time       Decoded   epoch ms (= end_tag.bin)
...     4     width               Decoded
...     4     height              Decoded
...     4     page_h_padding      Decoded
...     4     page_v_padding      Decoded
...     4     min_format_version  Decoded
...     4     title_size          Decoded   length of title blob
...     ...   title_blob          Partial   title text scanned from within
```

### `meta_flags`
The only bit promoted to a clean semantic is **`0x2000` = has-tables**: set on
exactly the 2 table-bearing notes and unset on the other 11 (including
typed-but-tableless), agreeing with independently parsed table cells. The rest
of the observed values (`0xc0a80`, `0xc2a80`, `0xc8e80`, `0xcae80`, `0xc0e80`)
are combinations of constant base bits plus `0x2000`; `0x400` and `0x8000` were
tested against wider observables and show no clean feature, so they stay
**Unknown**.

### `format_version` / family
`format_version` is `4000` (9 files) or `5400` (4 files) and matches
`end_tag.bin`. Combined with `flags` and `meta_flags` it partitions the corpus
into note families (e.g. `fmt5400/flags0x8/meta0xc0a80` = typed-text notes;
`meta0xc2a80`/`meta0xcae80` add tables/voice). These families are descriptive
groupings, not a decoded field.

### `title_blob`
`title_size` frames a title object blob whose inner schema is only partially
understood; the reference parser scans the visible title text out of it. Modeled
only by its size in the `.ksy`.

## Validation

```bash
KSC_GEN=<scratch>/gen .venv/bin/python spec/tools/validate_note.py
# -> 13 matched, 0 mismatched, out of 13 parsed
```

Compares every scalar header field plus `note_id` against `parse_note_metadata`.
Toolchain: [`../../../../spec/README.md`](../../../../spec/README.md).
