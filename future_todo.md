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
  | end_tag document_height == note.note height | 13/13 |
  | mediaInfo record tail structure | 60/60 records |
  | `.page` header | 48/48 pages |
  | `.page` layer/object tree | 48/48 pages, 11788/11788 objects |
  | object header (field_flags additive model) | 11788/11788 objects |
  | payload-geometry wrapper | 412/412 |
  | page-footer-hash == pageIdInfo manifest hash | 48/48 |
  | head_hash == note.note[-32:] | 13/13 |
  | note.note fixed tail anchors | 13/13 |

- **Recent decodes:** `sdocx_page.ksy` now models the `.page` layer/object tree
  structurally (layers, optional content fields, recursive object entries,
  object blob substreams, and layer hashes) and validates all object boundaries
  against `parse_page_tree`. `sdocx_note.ksy` now models only the fixed
  `note.note` tail anchors: the `offset_to_data` sentinel, the EOF-relative
  tail-hash-block candidates, and `note.note[-32:]`.

- `end_tag.bin` offset 26 is decoded as `document_height` (`f32`), matching
  `note.note.height` on 13/13 samples. This is the stacked document/note height,
  not a per-page height.

- `mediaInfo.dat` record tails are now structurally decoded as
  `[u16 tag][u64 time_candidate][u8 marker]` on 60/60 records; `marker == 1` on
  all records. `tag` and `time_candidate` semantics remain Unknown: the time
  candidate exactly matches neither note created/modified nor ZIP entry time.

- `note.note` `tail_post_hash_u32` is now decoded as a copy of the trailing
  four bytes (`u32le(note.note[-4:])`) on all 3/3 occurrences; why only shifted
  tail-hash samples carry it remains open.

- Timestamp-ish diagnostics are captured in `spec/tools/analyze_time_fields.py`.
  `end_tag.created_time_header` is exact on 13/13; `created_time_a/b` are exact
  on 10/13 and divergent on the 3 older/imported samples; `extra_time_candidate`
  is non-zero on only 2/13 and does not equal note modified time.

- Absolute-f64 stroke investigation has started in
  `spec/tools/analyze_absolute_f64_strokes.py`. Default corpus scan:
  11,375 stroke objects, 11,353 delta-consistent and skipped, 22 scanned as
  suspicious, 0 absolute-f64 candidates found. Keep the variant open pending
  a targeted sample or a stronger signature.

- `pageIdInfo.dat` is a *manifest of copied hashes* —
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

## Completed task 1 — model the `.page` layer/object tree in Kaitai

Done in `spec/ksy/sdocx_page.ksy`, `spec/tools/validate_page_tree.py`, and
`tests/test_kaitai_spec.py::test_page_tree`. The validator walks the Kaitai tree
and checks layer/object boundaries (`off`, `blob_off`, `end`), counts, raw types,
blob sizes, recursive child order, and layer hashes against `parse_page_tree` /
`_parse_objects` in [`pysdocx/page.py`](./pysdocx/page.py).

## Completed task 2 — model the `note.note` tail (partial, honest scope)

Done in `spec/ksy/sdocx_note.ksy`, `spec/tools/validate_note.py`, and
`tests/test_kaitai_spec.py::test_note_header`. The `.ksy` models only fixed
boundaries: `tail_sentinel` at `offset_to_data`, `trailing_hash` at
`note.note[-32:]`, and the two EOF-relative `tail_hash_block` candidate windows
observed in the corpus (EOF-aligned, or followed by a 4-byte post-hash u32).
`pen_preload_path`, `pen_style_tail`, and voice records remain documented
procedural scans because they are marker-found, not fixed-offset records.

## Next tasks

- Keep expanding only zero-counterexample structural fields in Kaitai; marker
  scans stay in `pysdocx` + docs until a fixed boundary is proven.
- When the user wants a targeted sample campaign, isolate `HDR_EXT.counter` with
  a controlled note: create one shape, duplicate it, modify one copy, copy it to
  another page, and compare which counters persist/change. This should separate
  object lineage vs group lineage vs copy/edit generation.
- Lower-priority backlog remains below.

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
- **`mediaInfo.dat` record tail semantics**, remaining **`end_tag.bin` middle fields**,
  **`ext_block.seq`/`counter`**: bounded but not semantically named; need
  isolated samples.

## Discipline

`pysdocx`-first; port to Rust only at checkpoints. Promote a byte only with zero
corpus counterexamples; keep decoded facts separate from render heuristics
(`heuristics.md`) and never put heuristics in a `.ksy`. When you decode something,
extend the `.ksy` + its validator + the `docs/format/**` page together. **Never
commit without the user's explicit OK.**
