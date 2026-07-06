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
  explores remaining `tag` / `time_candidate` semantics.
- **Conventions:** [`../00-conventions.md`](../00-conventions.md).

## At a glance

Little-endian. Header, length-prefixed records, trailer — fully decoded, zero
counterexamples across the corpus (60 records over 13 files; 60/60 point at
existing members and every SHA-256 verifies).

```
offset  size  field           status
0       4     magic           Decoded   0x1518 (x12) / 0x1452 (x1)
4       2     record_count    Decoded
6       ...   media_record[]  Decoded   record_count records
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
...     11         tail          Structural [u16 tag][u64 time][u8 marker]
```

## Decoded fields

### `magic` — `u32` @ 0
Manifest magic. Corpus values `0x1518` (×12) and `0x1452` (×1, on
`handwritten.sdocx`). Both parse identically; the difference tracks the same
old-import family seen in `end_tag.bin`.

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
Always `EOFX`, immediately after the last record (`bad_eof = 0`), and the file
ends there.

### `body.tail` — 11 bytes
The tail is structurally fixed on 60/60 corpus records:

```
u16 tag
u64 time_candidate
u8  marker
```

`marker` is constant `1` on 60/60. `tag` values are `1` ×54, `3` ×4, `5` ×1,
`20` ×1. The tag correlates partly with media kind (`3` appears on four `.jpg`
records, `5` on one `.jpg`, `20` on one `.pdf`), but not cleanly enough to name.
`time_candidate` is timestamp-like and near note/media edit times, but it is not
identical to the note created/modified times. The structure is Decoded; the
semantics of `tag` and `time_candidate` remain Unknown.

Corpus diagnostics:

```bash
.venv/bin/python spec/tools/analyze_media_tail.py samples
```

Current negative/partial results:

- `time_candidate` exactly matches neither `note.note.created_time`, nor
  `note.note.modified_time`, nor ZIP entry time on any of the 60 records.
- Per file, the latest `time_candidate` is often close to the note modified time
  (from -176 µs to about -2.1e9 µs in the current corpus), so it plausibly tracks
  media import/edit time, but not tightly enough to promote a semantic name.
- `tag` is not simply file extension: `tag=1` covers `.spi`, `.spp`, `.jpg`,
  `.png`, `.pdf`, `.m4a`, and nested `.sdocx`; non-1 tags appear only on a small
  set of `.jpg` / `.pdf` records.

## Unknown regions

There is no unbounded raw region left in `mediaInfo.dat` on the current corpus:
the former `raw_tail` is now structurally decoded. The remaining Unknowns are
semantic, not boundary-related: `tail.tag` and `tail.time_candidate`.

## Validation

```bash
KSC_GEN=<scratch>/gen .venv/bin/python spec/tools/validate_media_info.py
# -> 13 matched, 0 mismatched, out of 13 parsed
```

The check compares `magic`, `record_count`, the `EOFX` trailer, and every
record's `media_index`, `name`, `sha256`, `tail.tag`, `tail.time_candidate`, and
`tail.marker` against the reference `pysdocx` parser. See
[`../../../spec/README.md`](../../../spec/README.md) for the toolchain.
