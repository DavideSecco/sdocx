# Checkpoint & next tasks (handoff)

Start with [`CLAUDE.md`](./CLAUDE.md) (repo map, discipline, run commands) and
[`docs/format/`](./docs/format/) (the format knowledge base). This file is the
running "where we are + what's next". Last updated: 2026-07-06.

## Where we are

The **outer/container format is essentially fully decoded**, and the decoded
structure is now backed by an executable spec:

- **Kaitai spec + test gate** ([`spec/`](./spec/), `tests/test_kaitai_spec.py`):
  each `spec/ksy/*.ksy` is compiled to a Python parser (vendored in
  `spec/generated/`) and cross-checked field-by-field against `pysdocx` on the
  whole corpus. All pass with **zero counterexamples**:

  | Surface | Coverage |
  |---|---|
  | end_tag / pageIdInfo / mediaInfo / note-header | 13/13 |
  | `.page` header | 48/48 pages |
  | object header (field_flags additive model) | 11788/11788 objects |
  | payload-geometry wrapper | 412/412 |
  | page-footer-hash == pageIdInfo manifest hash | 48/48 |
  | head_hash == note.note[-32:] | 13/13 |

- **Recent decodes:** `pageIdInfo.dat` is a *manifest of copied hashes* —
  `head_hash = note.note[-32:]`, `page_hash = the .page footer hash` (the 32
  bytes just before the ASCII `Page for SAMSUNG S-Pen SDK` footer signature).
  Both linkages are decoded and gate-checked; only the *construction* of the
  underlying 32-byte hash is still open (see Negative results).

## Toolchain for spec work (needed for tasks below)

The generated parsers are vendored, so the **test gate needs only** the
`kaitaistruct` runtime (a dev dep): `.venv/bin/python -m unittest discover -s tests`.

To **edit a `.ksy`** you need the compiler once (kept out of the repo):

```bash
npm install --prefix <scratch> kaitai-struct-compiler js-yaml
# after editing spec/ksy/*.ksy:
NODE_PATH=<scratch>/node_modules spec/tools/regenerate.sh
.venv/bin/python -m unittest tests.test_kaitai_spec
```

Full recipe: [`spec/README.md`](./spec/README.md). Never commit
`spec/generated/` staleness — always regenerate after a `.ksy` edit.

## Next task 1 — model the `.page` layer/object tree in Kaitai

Goal: extend `spec/ksy/sdocx_page.ksy` (or a new `sdocx_page_tree.ksy`) to parse
the layer/object tree, so the whole `.page` traversal is executable + validated,
not just header + isolated objects. Reference: `parse_page_tree` / `_parse_objects`
in [`pysdocx/page.py`](./pysdocx/page.py); doc:
[`docs/format/container/page/README.md`](./docs/format/container/page/README.md).

Layout (all little-endian), starting at the page header's `base` (u32 @ 0x00):

```
u16 layer_count
u16 current_layer_index
layer_count x layer:
  u32 layer_prefix
  u32 next_offset
  u8  flag1, u8 flag2, u8 flag3, u8 content_flags
  u32 layer_flags
  # content_flags-gated optional fields, in this order:
  if 0x01: 1 byte
  if 0x02: 4 bytes
  if 0x04: u16 char_len + UTF-16LE string
  if 0x08: u16 char_len + UTF-16LE string  (layer_uuid)
  if 0x10: s64 modified_time
  if 0x20: 4 bytes
  u32 object_count
  object_count x object_entry   (see below)
  32-byte layer_hash

object_entry (OBJECT_ENTRY_LEN = 7, then blob, then recursive children):
  u8  raw_type
  s16 child_count
  u32 blob_size
  blob_size bytes  blob   # starts with the common object header (sdocx_object_header)
  child_count x object_entry   # recursion AFTER the blob (depth cap 16 in pysdocx)
```

Kaitai notes:
- Use a substream (`size: blob_size`) for the blob; you can reference
  `sdocx_object_header` as its type via an import to model the header inside.
- Recursion: an `object_entry` type that repeats `object_entry` child_count times.
- Validate by walking the tree with `parse_page_tree` and asserting the Kaitai
  layer/object boundaries (offsets, counts, raw_type, blob_size, layer_hash)
  match. Add a `validate_page_tree.py` and a `test_page_tree` gate method mirroring
  the existing ones.

## Next task 2 — model the `note.note` tail (partial, honest scope)

Reference: `scan_note_tail_records` in [`pysdocx/note.py`](./pysdocx/note.py); doc:
[`docs/format/container/note-note/tail-records.md`](./docs/format/container/note-note/tail-records.md).

Important: the tail is **marker-scanned**, not a fixed sequence, so a `.ksy`
cannot model all of it. Model only the parts with fixed boundaries and leave the
rest documented:
- `tail_sentinel` (fixed 16-byte pattern at `offset_to_data`).
- `tail_hash_block` and the note's trailing 32 bytes (= pageIdInfo `head_hash`).
- Keep `pen_preload_path`, `pen_style_tail`, voice records as documented
  procedural scans (they are found by markers, not fixed offsets).
If task 2 turns out to be mostly procedural, the right outcome is a *sharper doc*
plus a small `.ksy` for the sentinel/hash boundaries — do not force marker scans
into Kaitai.

## Negative results (don't redo)

- **The 32-byte content hash construction** (stored at `note.note[-32:]` and each
  `.page` footer, then copied into `pageIdInfo.dat`): NOT reproduced by any plain
  `sha256`/`sha3_256`/`blake2b` of the raw member, and a full contiguous-range
  brute force over the smallest page found nothing. Likely a canonical/serialized
  input or a keyed HMAC (device/app secret → unrecoverable from files). Low
  priority.

## Lower-priority backlog

- **Rotated in-page text-box wrapping** is still a render *heuristic*
  (`_text_box_layout` inner-wrap inset), not a decoded field — see
  `docs/format/heuristics.md`. Only worth revisiting with a dedicated
  `0/90/180/270°` text-box sample family.
- **Absolute-f64 stroke variant**: a couple of benchmark pages store stroke
  coordinates as absolute f64 pairs (not deltas); neither known layout reads them.
  This is the main visible handwriting-fidelity gap, but it is render-side and was
  deprioritized by the user.
- **Audio→media schema**: `voice_clip` links to a `.m4a` media index as a
  diagnostic; a full schema needs more audio samples.
- **`mediaInfo.dat` record raw tail**, **`end_tag.bin` middle fields**,
  **`ext_block.seq`/`counter`**: bounded but not semantically named; need
  isolated samples.

## Discipline

`pysdocx`-first; port to Rust only at checkpoints. Promote a byte only with zero
corpus counterexamples; keep decoded facts separate from render heuristics
(`heuristics.md`) and never put heuristics in a `.ksy`. When you decode something,
extend the `.ksy` + its validator + the `docs/format/**` page together. **Never
commit without the user's explicit OK.**
