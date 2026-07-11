# Checkpoint & next tasks (handoff)

Start with [`CLAUDE.md`](./CLAUDE.md) (repo map, discipline, run commands) and
[`docs/format/`](./docs/format/) (the format knowledge base). This file is the
running "where we are + what's next". Last updated: 2026-07-11.
The top-level regression corpus is now **28 samples / 192 pages**; generated inventory and golden
profiles were refreshed after the July 11 targeted-sample campaign (incl. the
`Tabella4x3Regolare` v1+v2 styled-table samples that cracked table styling
end-to-end — per-cell styling, fills, borders — now Kaitai-gated).

## Where we are

- **Math Solver + Web inline sample (NEW, 2026-07-11):**
  `Mathsolver&Hyperlink` closes the Web-object request: link previews are
  `text_core::Common` inline objects of type 13 (not page-layer objects),
  anchored by U+FFFC and backed by an `@web_*.jpg` thumbnail. Its hyperlink is
  therefore not span type 9. Math Solver does not emit formula span 23; it
  instead adds variable-sized `0x20` named properties associated with the
  recognised strokes (exact relationship Marker).
  `04 01 00 + RecogUIFeature_MathStrokeUuidStringArray` carries a counted array
  of UTF-16 stroke UUIDs. Python + Kaitai now decode these alongside the legacy
  32-byte scalar `extra_key_stroke_shape` form; `06/07` multi-property bags
  (expression/fail-code keys) are bounded but still raw. HDR_EXT remains
  dimension-clean.

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

- **Table styling FULLY decoded + Kaitai-gated (NEW, 2026-07-11):** the
  `Tabella4x3Regolare` v1+v2 samples (4×3 grid, one style change per page, PDF
  ground truth) cracked the whole table style model. **Per-cell character
  styling** — `font_size`, `bold`, `strikethrough`, `foreground_color` spans —
  confirms the `text_core` span-type names against ground truth for the first
  time. **Per-cell background fill** is the cell's `cell_fill_argb` u32 (was
  mis-asserted as "cell zero"; `sfondo blu` = `ffdaecfb`). **Custom column
  widths** = the `col_width` f32 array. **Style tail decoded (v2 border
  family):** first border block = outer frame, second = inner grid lines; per
  entry `ARGB + stroke width + corner radii` (26 → 0 on "bordi netti a 90°");
  entries 0/2 vertical, 1/3 horizontal; disabled borders zeroed; the trailing
  ARGB is the theme header beige and the f32 arrays are per-column width
  constraints (Marker). Field corrections: table-wrap `rows_minus_1` → 0-based
  **table_index**; cell-preamble `T5` 2nd byte = table-wide **styled flag**.
  Cell-bbox **Y origin** is document-stacked (dy = page_index × page_height)
  on geometry-edited tables, page-local otherwise — render Y relative to the
  wrap bbox. Merged cells are N/A (no UI action). The legacy render scan's
  overfit frame-size allowlist was replaced by a structural check; the scan is
  now a non-contradicting corroborator (structural parser authoritative).
  **New executable spec:** `spec/ksy/sdocx_table_object.ksy` +
  `spec/tools/validate_table_object.py`, gated in `test_kaitai_spec`
  (**20/20 tables, 260 cells, zero counterexamples**).

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

- **`.page` header preamble — field sequence DECODED, `content_bbox` gate DONE,
  template gates OPEN
  (2026-07-11):** the bytes before the paper
  record are now mapped — fixed `[obj_id][seq][4000][4000]` @0x70, then optional
  `content_bbox` / `template_uri` / `[u32 kind]`, then `[BGRA][width]` (= M),
  then the template fields. Full sequence + evidence in
  `docs/format/unknowns.md` (`.page`). Also surfaced a **third template
  mechanism**, `template_uri` (a custom-image path in the app's private
  storage). There is no bbox flag byte, but the gate is now formally decoded as
  `tree.has_objects` through a lazy Kaitai instance and cross-validated
  corpus-wide. The remaining template gates are still blocked: `kind` is absent
  only for the PDF family `base ∈ {0xa6,0xfd}` but `base` is downstream;
  `template_uri` only 4 pages/2 notes). So per the no-scans-in-a-.ksy rule the
  URI/kind/paper/template records STAY procedural (`_locate_paper_record`).
  `PaginaVuota&Paginapuntino_260711_122434.sdocx` proves the physical bbox
  omission with an intentional empty page vs one dot; `sdocx_page.ksy`, its
  validator, pysdocx, and Rust now expose it as optional.
  `PagLiscia&templatescustoms_260711_122117.sdocx` isolates the custom URI and
  embeds the matching JPG. Pysdocx + Rust/OpenSdocx now decode `CustomImage`,
  resolve the asset by basename, and render it beneath page content. The
  matching asset is embedded in both known cases (2/2), including the
  pre-existing `Appunti vari` sample — the earlier "not embedded" read (from
  before `template_uri` decoding existed) was never re-checked against it and
  turned out to be wrong; no genuinely-absent case has been observed.
- **PDF-backed templates (Academic multi-page + imported PDF) — link decoded
  AND rasterised (DONE, 2026-07-09):** `samples/Notebook&Planner1_260709_213306.sdocx`
  is the first "Academic" template sample (+ its `…_gt.pdf`). These are NOT
  procedural like Basic — the artwork is a **real PDF embedded under `media/`**
  (`0@07_StudyTemplates_A4_v2.pdf` 7pp, `2@01_PlannerTemplates_A4_v2.pdf` 6pp),
  and each `.page` references `(pdf_media_index, pdf_page_index 0-based)` in the
  8 bytes after the paper record (`flag@M+8==1 & reserved@M+0xC==0`, media@M+0xA,
  page@M+0xE). Decoded in `page_pdf_template`; `page_template` now returns
  `{kind:"pdf", pdf_media_index, pdf_page_index}`. Zero counterexamples over the
  150-page corpus, and it **fixes a bug**: `quiz.sdocx`'s imported-PDF page was
  mislabelled "Lined (narrow)". Also refactored `page_background_color` onto a
  shared `_locate_paper_record` (width-match fallback) so PDF-template pages
  resolve their white paper (they'd returned None). **Rasterisation done too:**
  `pysdocx.render.rasterize_pdf_page` (pypdfium2 — pdfium, the same engine the
  Rust app targets) rasterises the referenced embedded PDF page and composites
  it as the full-page background under the strokes; A4 aspect == page aspect so
  it fills with no distortion. Verified page-for-page against the exported
  `…_gt.pdf` (Notebook cover + label, Planner calendar + label, empty template
  pages). pypdfium2 is an *optional* render dep — without it the background is
  omitted (graceful), the link still decodes. Full write-up in
  `docs/format/container/page/README.md` ("PDF-backed templates"). Still open:
  `flag` semantics (always 1 — count for multi-template?), and PDF-filename →
  human catalog name (needs the Samsung Notes APK; separate concern, deferred).
  **Rust port DONE (2026-07-09):** `crates/sdocx/src/page.rs` now decodes the PDF
  link via the same shared `locate_paper_record` (width fallback) +
  `page_pdf_template` (flag/reserved/media/page), `PageTemplateSource::CustomPdf`
  gained `media_index`; verified on the real Notebook file via sdocx-cli (media 0
  pages 0-6, media 2 pages 0-5+dup, matches pysdocx) and quiz now reads as PDF not
  "Lined". Full workspace + opensdocx green. The actual app-side PDF *rasterisation*
  (SceneTemplate already has a "pdf" kind; now has media+page to feed pdfium) is the
  remaining app work, not a decode gap. Basic category/name/pitch stays pysdocx/
  Scene-side (render heuristic), not in the core crate.
- **Basic background templates named + rendered, all categories except id 10
  (DONE, 2026-07-09):** `samples/AlltypeofPageBasic_260709_200911.sdocx`
  cycles through Samsung Notes' "Basic" background picker, one id per page,
  each hand-labelled by the user with the on-device name; a matching photo set
  landed in `samples/AllTypeofPageBasic/` (11 GT photos, one per non-blank
  page) and pinned every pitch by direct pixel measurement (line-projection
  for rules, blob-centroid clustering for dots). `TEMPLATE_NAMES` (id →
  category/name, decoded fact) plus `GRID_SPACING_BY_ID` (now 4/5/6)/
  `LINE_SPACING_BY_ID`/`DOT_SPACING_BY_ID`/`OXFORD_LINE_SPACING`+
  `OXFORD_MARGIN_X`/`_COLOR` (all heuristic/calibrated) are in
  `pysdocx/page.py`; `render.py` gained `draw_lines`/`draw_dots`/`draw_oxford`
  and `render_page` now dispatches on `template["kind"]` for all four
  categories. Verified by re-rendering the sample and eyeballing each page
  against its GT photo — pitch and layout match. Full table + finding that
  line/grid share one narrow/default/wide triple (72.5/102.5/168.0) while dot
  is a genuinely non-square lattice (~7-10% wider columns) in
  `docs/format/container/page/README.md` and `heuristics.md`. **id 10 is
  still missing** — never appeared in the sample, needs a dedicated capture
  (its category and pitch are both unknown). `GRID_ORIGIN` (top margin) was
  reused as-is for the new categories, not independently re-measured — worth
  a sanity check if a rendered line/dot/oxford page looks vertically off.
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
  `Shared Notebook1_260710_000433.sdocx` exercises `attached_files` and
  `server_check_point`, but not `author_info`/`app_name`/`app_version`. It also
  adds a framed `CONTENT_FILE_DATA_LIST` collaboration extension to
  `mediaInfo.dat`; outer framing is now modeled, inner COEDIT metadata remains
  Unknown.
- **Bookmarks sample explored (2026-07-11; negative export result):** pages 1
  and 3 of `Segnalibri_260709_225650.sdocx` are bookmarked, page 2 is not, but
  their serialized page/note/manifest structures expose no bookmark-specific
  field. The only tempting `0,2,1` values are now decoded as ordinary `.spi`
  thumbnail media indices (12/12 cross-file). Treat bookmarks as not exported
  unless a future controlled pair changes bytes outside hashes/thumbnails.
- **Three more targeted samples closed (2026-07-11):** `Default-darkmode-
  Liscio_260711_153256.sdocx` confirms `note.note` `property_flags` bit 0x8
  = `is_background_colour_inverted` (was Marker, now Decoded — docs updated
  in `container/note-note/README.md`). `Importedlandscape_260711_153103.sdocx`
  gives a genuinely landscape page (1600×928, builtin "Landscape Grid" PDF
  template) but `end_tag.bin`'s `is_landscape` bit stays 0 — closed as a
  negative result (the flag is decoupled from page aspect ratio). Basic
  template id 10 confirmed by the user not to exist in the current app —
  dropped from the wishlist, not a gap. Also checked `samples/
  samsung2.sdocx.zip` (a real Android/Galaxy-Tab export from
  `squ1dd13/sdocx2pdf#1` where it reportedly crashes that unrelated tool):
  parses 100% cleanly here, zip framing is unremarkable — external
  validation, not a new decode. The sample wishlist moved from agent memory
  to `docs/format/sample-wishlist.md` (repo-visible, at the user's request)
  and is now the canonical status list — see it for the next concrete
  table-style-tail sample spec (4 files: merged cells / custom borders /
  custom widths-heights / cell shading, each vs. a plain-grid baseline).
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
  `TextboxAllAngles_260709_231912.sdocx` now validates rotation storage and
  midpoint geometry at all eight 45° increments (`315°` stored as `-45f`), but
  its four-character text cannot calibrate wrapping; a long identical string
  and identical box dimensions are still needed for that part.
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

**Adding a sample** (the user drops new `.sdocx` into `samples/` often): the
regression suite's corpus-dependent counts live in a golden snapshot, so you no
longer hand-edit numbers. Run `.venv/bin/python -m tests.regen_golden`, review the
JSON diff (an *unexpected* change is a real regression, not a number to bless), and
commit `tests/golden/corpus_profiles.json`. The corpus-independent invariants
(zero unknown bytes / zero sha mismatches / per-file == SAMPLE_COUNT / matches ==
surfaces) stay asserted in code — `CorpusProfileTest.test_invariants` — and can't
be regenerated away. See `tests/golden.py`.
