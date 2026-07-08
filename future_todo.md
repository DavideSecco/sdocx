# Checkpoint & next tasks (handoff)

Start with [`CLAUDE.md`](./CLAUDE.md) (repo map, discipline, run commands) and
[`docs/format/`](./docs/format/) (the format knowledge base). This file is the
running "where we are + what's next". Last updated: 2026-07-08.
The corpus is now **14 samples** (a heavily-illustrated 14th sample joined; all
hardcoded corpus counts in the regression tests were refreshed).

## Where we are

The **outer/container format is essentially fully decoded**, and — new —
**`note.note` is now sequentially decoded end-to-end**, backed by an
executable spec:

- **`note.note` note-doc structure (NEW, 2026-07-08):** the whole member
  parses as one sequential structure — header, two variable-length bitfields
  (`meta_flags` turned out to be the **field-flags bitfield** gating the tail
  "flex fields"), title/body Text blobs, and flag-gated flex fields (string
  registry, pen records, voice recordings, attached files, …) ending exactly
  at the trailing hash on **14/14**. All legacy marker-scanned "tail records"
  are explained as flex fields (pen preload paths = pen names + string
  registry; param hints = `advanced_settings`; voice clips = structured voice
  recordings with start/stop events; the tail sentinel = the first three flex
  fields; the hash-block prefix pair = `fixed_text_direction` +
  `fixed_background_theme`). **Correction:** `meta_flags 0x2000` is
  `voice_data`, NOT has-tables. Reference parser `pysdocx/note_doc.py`
  (+ CLI `note-doc`), spec `spec/ksy/sdocx_note.ksy`, validator
  `spec/tools/validate_note.py`, cross-check diagnostic
  `spec/tools/analyze_note_doc.py`, docs `docs/format/container/note-note/`.
- **`text_core::Common` rich-text frames (NEW, 2026-07-08):** the title/body
  blobs carry an exactly-sized frame: text, span vector, paragraph vector,
  margins, gravity, section data, inline objects. The TLV style/paragraph
  scans are these records byte-for-byte (`18 00 <tag> 00` = 24-byte span,
  strikethrough = 20-byte span type 20, `1c 00 05 00` = bullet paragraph);
  span payloads carry the color/f32/bool + a constant zero u32. Table cells
  are **nested Common frames** inside a type-22 inline object anchored at a
  U+FFFC char (anchor == `position` 3/3); an inline image is object type 3.
  Structural-vs-scan equality holds corpus-wide (zero counterexamples).

- **Type-22 table object (NEW, 2026-07-08):** the table object's body is now
  decoded **byte-exactly end-to-end** (`parse_table_object` in
  `pysdocx/note_doc.py`): sized wrapper/midpoints/outline records, column
  widths, length-chained rows and cells with page-coords bboxes, per-cell
  uuid + outline path + nested Common frame, and a style tail (border blocks,
  per-column arrays, colors — positions decoded, semantics pending a styled
  table family). The old scan's "anchor + u16 6" marker = the cell outline's
  last path point + the path closepath opcode. Validated 2/2 notes, 18/18
  cells (`analyze_note_doc.py`, regression-gated).

- **Kaitai spec + test gate** ([`spec/`](./spec/), `tests/test_kaitai_spec.py`):
  each `spec/ksy/*.ksy` is compiled to a Python parser (vendored in
  `spec/generated/`) and cross-checked field-by-field against `pysdocx` on the
  whole corpus. All pass with **zero counterexamples**:

  | Surface | Coverage |
  |---|---|
  | end_tag / pageIdInfo / mediaInfo / note-doc | 14/14 |
  | end_tag document_height == note.note height | 14/14 |
  | mediaInfo record tail structure | 222/222 records |
  | `.page` header / layer-object tree | all pages/objects |
  | payload-geometry wrapper | 490/490 |
  | page-footer-hash == pageIdInfo manifest hash | all pages |
  | head_hash == note.note[-32:] | 14/14 |
  | note.note full sequential structure | 14/14 |

- **Recent decodes:** `sdocx_page.ksy` models the `.page` layer/object tree
  structurally (layers, optional content fields, recursive object entries,
  object blob substreams, and layer hashes) and validates all object boundaries
  against `parse_page_tree`. `sdocx_note.ksy` now models the **whole**
  `note.note` member sequentially (see the note-doc bullet above).

- `end_tag.bin` offset 26 is decoded as `document_height` (`f32`), matching
  `note.note.height` on 13/13 samples. This is the stacked document/note height,
  not a per-page height.

- `end_tag.bin` is now decoded as the sequential S Pen SDK footer cross-checked
  against `sdocx2pdf`: note UUID, property flags, cover image, note size, app
  version, min format version, created time, page model, document type, owner,
  display timestamps, fixed text/theme settings, server checkpoint, orientation,
  optional app custom data, and signature all validate on 13/13. The legacy
  `handwritten.sdocx` footer omits the final zero-length app-custom-data field.

- `mediaInfo.dat` record tails are now decoded as
  `[u16 ref_count][u64 modified_time][u8 is_attached]` on 60/60 records,
  cross-checked against `sdocx2pdf`. `is_attached == true` on all records;
  `modified_time` is timestamp-like but does not exactly match note
  created/modified or ZIP entry time on the current corpus.

- `note.note[-32:]` is now decoded as `sha256(note.note[:-32])` on 13/13
  samples; `pageIdInfo.dat.head_hash` is a copy of that digest.

- `note.note` `tail_post_hash_u32` / shifted tail-hash-block windows are
  superseded: they were scan artifacts of what is now the exact flex-field +
  trailing-hash structure (`docs/format/container/note-note/tail-records.md`).

- Timestamp-ish diagnostics are captured in `spec/tools/analyze_time_fields.py`.
  `end_tag.created_time_header` is exact on 13/13;
  `display_created_time` / `display_modified_time` are exact on 10/13 and
  divergent on the 3 older/imported samples;
  `last_recognised_data_modified_time` is non-zero on only 2/13 and does not
  equal note modified time.

- `spec/tools/analyze_sdocx2pdf_leads.py` tracks not-yet-promoted
  `sdocx2pdf` leads and sample gaps: `end_tag` variant gaps are all zero-hit
  (no landscape, non-empty SDK strings, skipped/encryption blocks, or custom
  data); image media-ref `u32` hits 59/59; painting/drawing media-ref `u32`
  hits 1/1; voice clips link to `.m4a` mediaInfo records 2/2, with 0 page
  object type-10 audio objects. The note-level `text_core::Common` lead has
  been fully promoted (see above); the **page text-box** Common-like frame
  still hits only 2/8 at the blob level and stays a lead.

- Absolute-f64 stroke investigation has started in
  `spec/tools/analyze_absolute_f64_strokes.py`. Default corpus scan:
  11,375 stroke objects, 11,353 delta-consistent and skipped, 22 scanned as
  suspicious, 0 absolute-f64 candidates found. Keep the variant open pending
  a targeted sample or a stronger signature.

- `pageIdInfo.dat` is a *manifest of copied hashes* —
  `head_hash = note.note[-32:] = sha256(note.note[:-32])`, and `page_hash = the
  .page footer hash` (the 32 bytes just before the ASCII
  `Page for SAMSUNG S-Pen SDK` footer signature). The note hash construction is
  decoded; only the page footer hash construction remains open.

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

## Completed task 2 — model `note.note` end-to-end (supersedes the tail-anchor model)

Done in `spec/ksy/sdocx_note.ksy`, `pysdocx/note_doc.py`,
`spec/tools/validate_note.py`, `spec/tools/analyze_note_doc.py`, and
`tests/test_kaitai_spec.py::test_note_doc` +
`tests/test_pysdocx_regressions.py::NoteDocStructuralTest`. The `.ksy` now
models the whole member sequentially (flex fields gated by `field_flags`);
the old tail anchors (`tail_sentinel`, EOF-relative `tail_hash_block`
windows, `tail_post_hash_u32`) are decoded/superseded — see
`docs/format/container/note-note/tail-records.md`. Only the Text/Shape
wrapper around the `text_core::Common` frames remains procedural; the type-22
table object's inner schema is now decoded too (see Next tasks), likewise
procedural pending the wrapper decode.

## Next tasks

- **Page text-box `text_core::Common`: DONE (2026-07-08).** The frame parses
  structurally on 8/8 text-box blobs at offset 386 (406 on rotated boxes —
  the 20 extra bytes are rotation-related wrapper fields), spans equal the
  scanned runs, stored inner margins are `[8,4,8,4]`. The old 2/8 figure was
  an exact-text-match artifact (the frame keeps trailing newlines).
  Follow-up: reconcile the renderer's rotated-wrap inset heuristic with the
  decoded margins; decode the wrapper prefix + 48-byte post-frame tail.
- **Type-22 table inline object schema: DONE (2026-07-08).** The whole object
  body parses **byte-exactly**: wrapper (uuid, 2 µs timestamps, page bbox,
  n_rows−1) + edge-midpoints + outline-path records, then a content region
  with `u32 n_cols + f32 col_widths`, length-chained rows (f32 height, index,
  n_cols) and cells (col index, page bbox, per-cell wrapper/midpoints/outline
  + the nested Common frame), and a style tail (bbox, 2 border blocks
  `4×[ARGB + 3f32]`, per-column f32 arrays, final ARGB). The legacy scan
  marker is fully explained: the "f64 anchor pair + u16 6" is the cell
  outline's last path point + the closepath opcode (paths: `01` moveto /
  `02` lineto / `06` close). Parser `parse_table_object`/`note_doc_tables`
  in `pysdocx/note_doc.py`; cross-check `spec/tools/analyze_note_doc.py`
  (`tables structural: 2/2 all-checks, 18/18 cells`, gated in
  `tests/test_pysdocx_regressions.py`); docs
  `docs/format/container/note-note/tables.md`. No `.ksy` change: the table
  lives inside the body blob, which stays opaque in Kaitai until the
  Text/Shape wrapper is decoded (same boundary as the Common frames).
  Follow-ups: style-tail *semantics* (borders/floats/arrays) need a
  **styled-table sample family** (custom borders, widths, merged cells,
  shading); the renderer can now take grid geometry from the structural
  parse instead of anchor clustering.
- **Targeted samples for unexercised flex fields:** a note with a template,
  a shared/authored note, and an attached (non-image) file would exercise
  `template_uri`, `author_info`/`app_name`, `attached_files`.
- **Styled-table sample family** (unlocks the table style-tail semantics —
  the framing is done, only the defaults never varied): vs a plain grid, one
  change per sample — merged cells; custom border color/thickness; different
  column widths / row heights; cell background shading. Only-table, no audio.
- Keep expanding only zero-counterexample structural fields in Kaitai; marker
  scans stay in `pysdocx` + docs until a fixed boundary is proven.
- When the user wants a targeted sample campaign, isolate `HDR_EXT.counter` with
  a controlled note: create one shape, duplicate it, modify one copy, copy it to
  another page, and compare which counters persist/change. This should separate
  object lineage vs group lineage vs copy/edit generation.
- Lower-priority backlog remains below.

## Negative results (don't redo)

- **The `.page` footer 32-byte hash construction** (copied into
  `pageIdInfo.dat.page_hash`): NOT reproduced by any plain
  `sha256`/`sha3_256`/`blake2b` of the raw page member, and a full
  contiguous-range brute force over the smallest page found nothing. Likely a
  canonical/serialized input or a keyed construction. The `note.note` trailing
  hash is no longer part of this negative result; it is `sha256(note.note[:-32])`.

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
  diagnostic (2/2 current clips); current pages contain 0 raw type-10 audio
  objects, so a full page-object schema needs more audio samples.
- **`mediaInfo.dat` reference-count / attached-flag edge semantics**,
  **`end_tag.bin` variant coverage** (landscape/non-empty SDK strings/custom
  data/skipped/encryption blocks), **image/painting flex fields**, and
  **`ext_block.seq`/`counter`**: bounded but still need isolated samples for
  semantic edge cases.

## Discipline

`pysdocx`-first; port to Rust only at checkpoints. Promote a byte only with zero
corpus counterexamples; keep decoded facts separate from render heuristics
(`heuristics.md`) and never put heuristics in a `.ksy`. When you decode something,
extend the `.ksy` + its validator + the `docs/format/**` page together. **Never
commit without the user's explicit OK.**
