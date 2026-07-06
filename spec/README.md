# `spec/` — formal `.sdocx` format definitions

Machine-checkable [Kaitai Struct](https://kaitai.io) definitions for the Samsung
Notes `.sdocx` container, plus the tooling that validates them against the
reference `pysdocx` parser on the sample corpus.

The narrative/evidence companion lives in [`../docs/format/`](../docs/format/).

## Layout

- `ksy/*.ksy` — the format definitions. One file per container member. Only
  **Decoded** structure goes here (zero-counterexample fields); heuristics and
  procedural decoding (e.g. stroke delta decompression) stay in the docs.
- `tools/compile_ksy.js` — compiles a `.ksy` to a Python parser via the
  `kaitai-struct-compiler` JS build.
- `tools/validate_*.py` — parse every corpus sample with the generated Kaitai
  parser and assert every decoded field matches `pysdocx`.

## Toolchain

The Kaitai compiler and Python runtime are not vendored. Install them once:

```bash
# JS compiler + YAML loader (kept out of the repo; a scratch dir is fine)
npm install --prefix <scratch> kaitai-struct-compiler js-yaml
# Python runtime for the generated parsers
uv pip install kaitaistruct        # or: pip install kaitaistruct
```

## Compile + validate a member

```bash
SCRATCH=<scratch>
NODE_PATH="$SCRATCH/node_modules" node spec/tools/compile_ksy.js \
    spec/ksy/sdocx_end_tag.ksy "$SCRATCH/gen"
KSC_GEN="$SCRATCH/gen" .venv/bin/python spec/tools/validate_end_tag.py
```

Expected output:

```
13 matched, 0 mismatched, out of 13 parsed
```

## Status

| Member | `.ksy` | Validator | Corpus |
|---|---|---|---|
| `end_tag.bin` | `ksy/sdocx_end_tag.ksy` | `tools/validate_end_tag.py` | 13/13 ✅ |
| `pageIdInfo.dat` | `ksy/sdocx_page_id_info.ksy` | `tools/validate_page_id_info.py` | 13/13 ✅ |
| `media/mediaInfo.dat` | `ksy/sdocx_media_info.ksy` | `tools/validate_media_info.py` | 13/13 ✅ |
| `note.note` (header) | `ksy/sdocx_note.ksy` | `tools/validate_note.py` | 13/13 ✅ |
| `<uuid>.page` (header) | `ksy/sdocx_page.ksy` | `tools/validate_page.py` | 48/48 pages ✅ |
