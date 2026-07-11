# `spec/` — formal `.sdocx` format definitions

Machine-checkable [Kaitai Struct](https://kaitai.io) definitions for the Samsung
Notes `.sdocx` container, plus the tooling that validates them against the
reference `pysdocx` parser on the sample corpus.

The narrative/evidence companion lives in [`../docs/format/`](../docs/format/).

## Layout

- `ksy/*.ksy` — the format definitions. One file per container member. Only
  **Decoded** structure goes here (zero-counterexample fields); heuristics and
  procedural decoding (e.g. stroke delta decompression) stay in the docs.
- `generated/*.py` — **vendored** Kaitai parsers compiled from `ksy/`. Checked in
  so the test gate needs no compiler (only the `kaitaistruct` runtime). Do not
  edit by hand — edit the `.ksy` and run `tools/regenerate.sh`.
- `tools/compile_ksy.js` — compiles one `.ksy` to a Python parser via the
  `kaitai-struct-compiler` JS build.
- `tools/regenerate.sh` — recompiles all `ksy/` into `generated/`.
- `tools/validate_*.py` — standalone CLI: parse every corpus sample with the
  generated Kaitai parser and print per-sample field matches vs `pysdocx`.

## Test gate (always-on)

`tests/test_kaitai_spec.py` is the real regression gate: it imports the vendored
`generated/` parsers and asserts every decoded field matches `pysdocx` on every
corpus sample. It needs only the pure-Python `kaitaistruct` runtime (a dev
dependency), no compiler, and skips cleanly if the runtime or samples are absent.

```bash
.venv/bin/python -m unittest tests.test_kaitai_spec
```

If a `.ksy` and `pysdocx` diverge — or `pysdocx` drifts — this fails.

## Editing a spec (regenerate loop)

Only needed when you change a `.ksy`. Install the compiler once (anywhere; kept
out of the repo):

```bash
npm install --prefix <scratch> kaitai-struct-compiler js-yaml
# then, after editing spec/ksy/*.ksy:
NODE_PATH=<scratch>/node_modules spec/tools/regenerate.sh
.venv/bin/python -m unittest tests.test_kaitai_spec
```

The standalone `tools/validate_*.py` default to `spec/generated/`; override with
`KSC_GEN=<dir>` to point at freshly compiled parsers elsewhere.

Expected validator output:

```
13 matched, 0 mismatched, out of 13 parsed
```

## Status

| Member | `.ksy` | Validator | Corpus |
|---|---|---|---|
| `end_tag.bin` | `ksy/sdocx_end_tag.ksy` | `tools/validate_end_tag.py` | 14/14 ✅ |
| `pageIdInfo.dat` | `ksy/sdocx_page_id_info.ksy` | `tools/validate_page_id_info.py` | 14/14 ✅ |
| `media/mediaInfo.dat` | `ksy/sdocx_media_info.ksy` | `tools/validate_media_info.py` | 14/14, 222/222 record tails ✅ |
| `note.note` (whole member, sequential) | `ksy/sdocx_note.ksy` | `tools/validate_note.py` | 14/14 ✅ |
| `<uuid>.page` (header + tree) | `ksy/sdocx_page.ksy` | `tools/validate_page.py`, `tools/validate_page_tree.py` | 114/114 pages ✅ |
| `.page` object header | `ksy/sdocx_object_header.ksy` | `tools/validate_object_header.py` | all corpus objects ✅ |
| `.page` payload geometry | `ksy/sdocx_payload_geometry.ksy` | `tools/validate_payload_geometry.py` | 490/490 wrappers ✅ |
| `note.note` type-22 table object | `ksy/sdocx_table_object.ksy` | `tools/validate_table_object.py` | 20/20 tables, 260 cells ✅ |
