# `end_tag.bin`

A fixed-shape footer record that closes a Samsung Notes `.sdocx` archive. One
per document.

- **Formal spec:** [`spec/ksy/sdocx_end_tag.ksy`](../../../spec/ksy/sdocx_end_tag.ksy)
  (Kaitai Struct; validated against the whole corpus — see [validation](#validation)).
- **Reference parser:** `parse_end_tag` in [`pysdocx/container.py`](../../../pysdocx/container.py).
- **Conventions:** see [`../00-conventions.md`](../00-conventions.md) for byte-order,
  types, and the `Decoded` / `Heuristic` / `Unknown` legend.

## At a glance

Little-endian throughout. Two size families occur in the corpus:

| Family | `payload_size` | Total file size | Signature offset | Files |
|---|---|---|---|---|
| Standard | `146` | 148 bytes | `126` | 12 / 13 |
| Legacy import (`handwritten.sdocx`) | `142` | 144 bytes | `122` | 1 / 13 |

The leading fields are contiguous and fully decoded. The bytes between the decoded islands are structurally bounded but not yet named (see [Unknown regions](#unknown-regions)); the footer constants and the ASCII signature are anchored from the **end** of the stream so both families parse with a single definition.

```
offset  size  field                    status
0       2     payload_size             Decoded   = file_size - 2
2       2     format_version           Decoded   = note.note format_version
4       4     reserved_at_4            Decoded   always 0
8       8     modified_time (s64)      Decoded   = note.note modified_time
16     ...    (raw island)             Unknown
22      2     page_width               Decoded   = page header width
...    ...    (raw island)             Unknown
42      2     format_version_dup       Decoded   = format_version
46      8     created_time_header      Decoded   = note.note created_time
...    ...    (raw island)             Unknown
72      8     created_time_a           Decoded   created-time candidate
80      8     created_time_b           Decoded   created-time candidate
88      8     extra_time_candidate     Decoded   timestamp-like, rarely set
...    ...    (raw island + footer)    Partial   see below
end-22  22    signature (ASCII)        Decoded   "Document for S-Pen SDK"
```

## Decoded fields

Each of the following holds across all 13 corpus samples with **zero
counterexamples**.

### `payload_size` — `u16` @ 0
Byte count of everything after this field: `payload_size == file_size - 2` on
13/13 files (`bad_size = 0`).

### `format_version` — `u16` @ 2
Matches `note.note`'s `format_version` on 13/13. Corpus values: `4000` (×9),
`5400` (×4). Repeated verbatim at offset 42 (`format_version_dup`).

### `modified_time` — `s64` @ 8
Epoch-milliseconds document modified time. Matches `note.note`'s
`modified_time` exactly on 13/13 (`modified_mismatches = 0`).

### `page_width` — `u16` @ 22
Equals the page-header page width on the current corpus. Lives inside an
otherwise-unnamed region, so it is decoded as an isolated island rather than as
part of a fully-mapped struct.

### `created_time_header` — `s64` @ 46
Creation-time candidate carried in the header region; matches `note.note`
`created_time` exactly on 13/13 (`created_time_header_exact = 13`).

### `created_time_a` / `created_time_b` — `s64` @ 72 / @ 80
Two further creation-time candidates. Both match the note creation time exactly
on the 10 newer samples; on the 3 older imports they read as millisecond-close
but not identical values. `created_time_a` and `created_time_b` are identical to
each other on the 10 newer samples.

### `extra_time_candidate` — `s64` @ 88
An additional timestamp-like value; non-zero on only 2 samples. Named
conservatively because two positives are not enough to fix its meaning.

### `signature` — 22-byte ASCII @ `end - 22`
Always the literal `Document for S-Pen SDK` (`bad_signature = 0`). Located from
the end of the stream, which is why a single spec parses both size families.

## Unknown regions

Structurally present, not yet semantically named. They are deliberately left
unmodeled in the `.ksy` rather than given speculative names:

- **`[16, 72)` minus the decoded islands** — `page_width` @22,
  `format_version_dup` @42 and `created_time_header` @46 sit inside this range;
  the surrounding bytes are exposed only as `raw_mid_hex` diagnostics by the
  reference parser.
- **`[96, footer)`** — bytes between the last decoded timestamp and the footer
  constants (`raw_between_times_and_footer_hex`).
- **Footer constants** — the reference parser locates a 16-byte pattern
  `02 00 00 00  02 00 00 00  ff ff ff ff ff ff ff ff` (two `u32(2)` then
  `s64(-1)`) before the signature, followed by zero padding
  (`raw_footer_padding_hex`). These are consistent but pattern-anchored rather
  than offset-anchored, so they are documented here but not yet promoted into
  the formal spec.

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
