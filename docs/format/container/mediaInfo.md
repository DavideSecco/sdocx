# `media/mediaInfo.dat`

The **media manifest**: one record per attachment stored under `media/`
(images, audio, thumbnails, nested sticky-memo `.sdocx`, PDFs…), each with its
index, archive filename, and a SHA-256 digest. Closed by the ASCII trailer
`EOFX`.

- **Formal spec:** [`spec/ksy/sdocx_media_info.ksy`](../../../spec/ksy/sdocx_media_info.ksy)
  (validated corpus-wide — see [validation](#validation)).
- **Reference parser:** `parse_media_info` / `list_media_info` in
  [`pysdocx/container.py`](../../../pysdocx/container.py).
- **Tail diagnostic:** [`spec/tools/analyze_media_tail.py`](../../../spec/tools/analyze_media_tail.py)
  explores timestamp relations for `modified_time`.
- **Conventions:** [`../00-conventions.md`](../00-conventions.md).

## At a glance

Little-endian. Header, length-prefixed records, trailer — fully decoded, zero
counterexamples across the corpus (60 records over 13 files; 60/60 point at
existing members and every SHA-256 verifies). Shared/COEDIT notes can add an
optional length-framed collaboration block before the trailer.

```
offset  size  field           status
0       4     format_version  Decoded   5400 (x12) / 5202 (x1)
4       2     record_count    Decoded
6       ...   media_record[]  Decoded   record_count records
...     ...   content_file_data_list Marker optional COEDIT extension
...     4     "EOFX"          Decoded   ASCII trailer
```

Each `media_record` is length-prefixed:

```
offset  size          field         status
0       4             payload_size  Decoded   size of body (excludes this field)
4       payload_size  body          Decoded   framed sub-stream (below)
```

And each `body`:

```
offset  size       field         status
0       4          media_index   Decoded   matches "<index>@" filename prefix
4       2          name_len      Decoded   UTF-16 char count
6       name_len*2 name          Decoded   UTF-16LE archive filename
6+n*2   64         sha256        Decoded   ASCII hex; verifies vs media/<name>
...     11         tail          Decoded   [u16 ref_count][u64 modified_time][u8 is_attached]
```

## Decoded fields

### `format_version` — `u32` @ 0
Manifest format version. Corpus values `5400` (`0x1518`, ×12) and `5202`
(`0x1452`, ×1, on `handwritten.sdocx`). This was previously named `magic`; the
independent `sdocx2pdf` parser reads the same field as the newer-format
`mediaInfo.dat` format version.

### `record_count` — `u16` @ 4
Number of `media_record`s before the `EOFX` trailer.

### `media_record.payload_size` — `u32`
Byte length of the record body, **excluding** this size field. This frames the
body as a bounded sub-stream, which is why a trailing `raw_tail` of unknown
length can be tolerated without desyncing the record loop.

### `body.media_index` — `u32`
The attachment's index. Matches the `<index>@` prefix of `name` on the corpus
(`index_matches_name`), and is the key used elsewhere to reference a specific
media file (e.g. image objects, voice clips).

### `body.name` — UTF-16LE
The archive-relative filename, already including the `<index>@...` prefix used
under `media/`. Corpus extensions: `.spi` (×44, S Pen thumbnails), `.jpg` (×7),
`.sdocx` (×3, nested sticky-memos), `.m4a` (×2, audio), `.pdf` (×2), `.png`
(×1), `.spp` (×1).

### `body.sha256` — 64-byte ASCII @ end of name
Lowercase hex SHA-256 of the referenced `media/<name>` file. Verified against
the actual archive bytes on **60/60** records (`sha_mismatches = 0`,
`missing_media = 0`, `unlisted_media = 0`).

### `eof` — 4-byte ASCII trailer
Always `EOFX`, after the ordinary records and the optional COEDIT extension,
and the file ends there.

### Optional `content_file_data_list` — Structural / Marker

`Shared Notebook1_260710_000433.sdocx` inserts the following block after its
ordinary media record and before `EOFX`:

```
30 bytes  "Q09OVEVOVF9GSUxFX0RBVEFfTElTVA"  unpadded base64 CONTENT_FILE_DATA_LIST
u32       record_count
repeat record_count:
  u32     payload_size
  bytes   body[payload_size]
```

The sample has one 570-byte body. The marker, count, framing, and final `EOFX`
boundary are decoded and modeled in Kaitai. The body's collaboration metadata
remains opaque until controlled shared-note variants isolate its fields.

### `body.tail` — 11 bytes
The tail is structurally fixed on 60/60 corpus records:

```
u16 ref_count
u64 modified_time
u8  is_attached
```

`sdocx2pdf` independently names these fields `_ref_count`, `_modified_time`, and
`is_attached`. The byte boundaries are decoded with zero counterexamples here.
`is_attached` is constant `1`/`True` on 60/60 corpus records. `ref_count` values
are `1` ×54, `3` ×4, `5` ×1, `20` ×1. `modified_time` is timestamp-like and near
note/media edit times, but it is not identical to the note created/modified
times or ZIP entry time on the current corpus.

Corpus diagnostics:

```bash
.venv/bin/python spec/tools/analyze_media_tail.py samples
```

Current negative/partial results:

- `modified_time` exactly matches neither `note.note.created_time`, nor
  `note.note.modified_time`, nor ZIP entry time on any of the 60 records.
- Per file, the latest `modified_time` is often close to the note modified time
  (from -176 µs to about -2.1e9 µs in the current corpus), so it plausibly tracks
  media import/edit time, but not tightly enough to promote a semantic name.
- `ref_count` is not simply file extension: `ref_count=1` covers `.spi`, `.spp`, `.jpg`,
  `.png`, `.pdf`, `.m4a`, and nested `.sdocx`; non-1 tags appear only on a small
  set of `.jpg` / `.pdf` records.

## Unknown regions

There is no unbounded raw region left in `mediaInfo.dat`: the former media-record
`raw_tail` is decoded and the COEDIT body is explicitly length-framed. The
remaining caveat is semantic variety:
`ref_count` and `is_attached` are named from the independent implementation, but
the current corpus does not vary attachment deletion/reference states enough to
stress those meanings.

## Validation

```bash
KSC_GEN=<scratch>/gen .venv/bin/python spec/tools/validate_media_info.py
# -> 13 matched, 0 mismatched, out of 13 parsed
```

The check compares `format_version`, `record_count`, the `EOFX` trailer, and
every record's `media_index`, `name`, `sha256`, `tail.ref_count`,
`tail.modified_time`, and `tail.is_attached` against the reference `pysdocx`
parser. See
[`../../../spec/README.md`](../../../spec/README.md) for the toolchain.
