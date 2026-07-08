# `end_tag.bin`

A sequential S Pen SDK footer record that closes a Samsung Notes `.sdocx`
archive. One per document.

- **Formal spec:** [`spec/ksy/sdocx_end_tag.ksy`](../../../spec/ksy/sdocx_end_tag.ksy)
  (Kaitai Struct; validated against the whole corpus — see [validation](#validation)).
- **Reference parser:** `parse_end_tag` in [`pysdocx/container.py`](../../../pysdocx/container.py).
- **Time diagnostic:** [`spec/tools/analyze_time_fields.py`](../../../spec/tools/analyze_time_fields.py)
  compares timestamp-like fields across `end_tag.bin`, `note.note`, and media tails.
- **Conventions:** see [`../00-conventions.md`](../00-conventions.md) for byte-order,
  types, and the `Decoded` / `Heuristic` / `Unknown` legend.

## At a glance

Little-endian throughout. Two size families occur in the corpus:

| Family | `payload_size` | Total file size | Signature offset | Files |
|---|---|---|---|---|
| Standard | `146` | 148 bytes | `126` | 12 / 13 |
| Legacy import (`handwritten.sdocx`) | `142` | 144 bytes | `122` | 1 / 13 |

The field names below are cross-checked against the independent `sdocx2pdf`
parser and validated against the current corpus. The ASCII signature is anchored
from the **end** of the stream so both size families parse with a single
definition; the legacy `handwritten.sdocx` footer omits the final zero-length
`app_custom_data` field before the signature.

```
offset  size  field                    status
0       2     payload_size             Decoded   = file_size - 2
2       4     format_version           Decoded   = note.note format_version
6       var   note_uuid                Decoded   short UTF-16 string; empty corpus-wide
8       8     modified_time (s64)      Decoded   = note.note modified_time
16      4     property_flags           Decoded   bit 1 = is_landscape; zero corpus-wide
20      var   cover_image              Decoded   short UTF-16 string; empty corpus-wide
22      4     note_width               Decoded   = page header width
26      4     document_height          Decoded   f32 = note.note height
30      var   app_name/version         Decoded   empty app name, version fields
42      4     min_format_version       Decoded   = format_version
46      8     created_time_header      Decoded   = note.note created_time
54      4     last_viewed_page_index   Decoded   zero corpus-wide
58      2     page_model               Decoded   0 paged/list, 1 pageless/single
60      2     document_type            Decoded   0 unlocked document corpus-wide
62      var   owner/skip/encryption    Decoded   empty/zero corpus-wide
72      8     display_created_time     Decoded   SDK display created time
80      8     display_modified_time    Decoded   SDK display modified time
88      8     last_recognised...       Decoded   non-zero on 2 samples
96      var   fixed_font               Decoded   empty corpus-wide
98      4     fixed_text_direction     Decoded   2 = default corpus-wide
102     4     fixed_background_theme   Decoded   2 = default corpus-wide
106     8     server_checkpoint        Decoded   -1 corpus-wide
114     4     new_orientation          Decoded   0 = portrait corpus-wide
118     4     min_unknown_version      Decoded   zero corpus-wide
122     var   app_custom_data          Decoded   optional long UTF-16 string; empty/omitted
end-22  22    signature (ASCII)        Decoded   "Document for S-Pen SDK"
```

## Decoded fields

Each of the following holds across all 13 corpus samples with **zero
counterexamples**.

### `payload_size` — `u16` @ 0
Byte count of everything after this field: `payload_size == file_size - 2` on
13/13 files (`bad_size = 0`).

### `format_version` — `u32` @ 2
Matches `note.note`'s `format_version` on 13/13. Corpus values: `4000` (×9),
`5400` (×4). The older parser exposed the low `u16`; the high half is zero on
the corpus.

### `modified_time` — `s64` @ 8
Samsung document modified timestamp. Matches `note.note`'s `modified_time`
exactly on 13/13 (`modified_mismatches = 0`).

### `note_width` / `document_height` — `u32` @ 22 / `f32` @ 26
`note_width` equals the page-header width on the current corpus; `page_width`
remains as a back-compat low-`u16` alias. `document_height` equals `note.note`'s
height on 13/13 samples. This is the document/note height (for multi-page notes,
the stacked note height), not the per-page `.page` height.

### SDK string / option fields
`note_uuid`, `cover_image`, `app_name`, `app_version_patch_name`, `owner_id`,
`fixed_font`, and `app_custom_data` are decoded as SDK length-prefixed UTF-16
strings. They are empty on the current corpus; the legacy footer reaches the
signature immediately after `min_unknown_version`, so `app_custom_data` is
omitted rather than encoded as a zero-length long string.

`app_version_major` and `app_version_minor` are both `0xffffffff` on the current
corpus. `skipped_size` and `encryption_data_size` are zero on 13/13.

### `created_time_header` — `s64` @ 46
Creation time carried in the SDK footer; matches `note.note`
`created_time` exactly on 13/13 (`created_time_header_exact = 13`).

### `page_model` / `document_type`
`page_model` is `0` for paged/list notes and `1` for pageless/single notes,
matching the enum names in `sdocx2pdf`. `document_type` is `0` on the current
corpus (`UnlockedDoc` in `sdocx2pdf`).

### `display_created_time` / `display_modified_time` — `s64` @ 72 / @ 80
SDK display timestamps. Both match the note creation time exactly on the 10
newer samples; on the 3 older imports they read as millisecond-close but not
identical values. These retain back-compat aliases `created_time_a` and
`created_time_b`.

`analyze_time_fields.py` confirms the split: `created_time_header` matches
`note.note.created_time` on 13/13, while `display_created_time` and
`display_modified_time` match exactly on 10/13 and diverge on the three
older/imported samples.

### `last_recognised_data_modified_time` — `s64` @ 88
Non-zero on only 2 samples. The two non-zero values do not equal
`note.note.modified_time`; they precede it by about 13.18s and 0.99s
respectively in the current corpus. Retains the back-compat alias
`extra_time_candidate`.

### Fixed settings and orientation
`fixed_text_direction` and `fixed_background_theme` are both `2` (`Default` in
`sdocx2pdf`) on 13/13. `server_checkpoint` is `-1`, `new_orientation` is `0`
(`Portrait`), and `min_unknown_version` is `0`.

### `signature` — 22-byte ASCII @ `end - 22`
Always the literal `Document for S-Pen SDK` (`bad_signature = 0`). Located from
the end of the stream, which is why a single spec parses both size families.

## Remaining caveats

- Property flag semantics are only cross-checked for the current zero value; a
  landscape sample is needed to validate bit 1 in practice.
- `display_created_time` / `display_modified_time` use a different apparent unit
  or conversion on the three older/imported samples.
- Non-empty SDK strings, skipped blocks, encryption data, and custom data are
  structurally modeled but not represented in the current corpus.

## Validation

The Kaitai spec is not hand-checked prose — it is compiled to a Python parser
and cross-checked field-by-field against the reference `pysdocx` parser on every
corpus sample:

```bash
# one-time toolchain (session scratchpad); see spec/README.md
NODE_PATH=<scratch>/node_modules node spec/tools/compile_ksy.js \
    spec/ksy/sdocx_end_tag.ksy <scratch>/gen
KSC_GEN=<scratch>/gen .venv/bin/python spec/tools/validate_end_tag.py
# -> 13 matched, 0 mismatched, out of 13 parsed
```

If a future sample makes the two parsers disagree, this check fails loudly —
that is the point. The spec is the *what*; this document is the *why* and the
*how sure*.
