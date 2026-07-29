# Checkpoint & next tasks (handoff)

Start with [`CLAUDE.md`](./CLAUDE.md) (repo map, discipline, run commands) and
[`docs/format/`](./docs/format/) (the format knowledge base). This file is the
running "where we are + what's next". Last updated: 2026-07-11.
The top-level regression corpus is now **28 samples / 192 pages**; generated inventory and golden
profiles were refreshed after the July 11 targeted-sample campaign (incl. the
`Tabella4x3Regolare` v1+v2 styled-table samples that cracked table styling
end-to-end — per-cell styling, fills, borders — now Kaitai-gated).

- **APK reverse engineering session, hypothesis to port (NEW, 2026-07-14):**
  a separate static-RE thread against the Samsung Notes app itself (decompiled
  code, native libs — kept out of this repo, see the untracked/gitignored
  `apk-re/` for the full write-up) found that `note.note`'s "unexercised flex
  fields" (`app_name`, `author_info`, `latitude_longitude`, `template_uri`,
  `compatible_last_pen_info`, `text_summarisation`, `stroke_group_size`,
  `app_custom_data` — all "0/corpus" in `unknowns.md`) are likely not
  fixed-position fields at all, but entries in a **generic 3-map property bag**
  (int-valued / string-valued / byte-buffer-valued, each keyed by a string
  name), gated by a 3-bit flag. Coincides with the `extra_key` variable
  property bag already partially decoded in a parallel session. **NEXT:** port
  this as a hypothesis into `pysdocx` and validate against the corpus
  (zero-counterexample discipline) before touching `docs/format/` or the
  `.ksy`. The same session also traced the *entire* native save pipeline for
  the `.page` footer hash and found nothing (see updated "Negative results"
  below) — that thread is paused per the user's call, don't redo the trace,
  just pick it up from `apk-re/04-ghidra.md` if revisited.
- **Shape/Text wrapper decoded + Kaitai-gated (NEW, 2026-07-12):** title/body
  Text blobs and raw type-2 page text boxes share the exact inheritance chain
  `ObjectBase(type 0) → ShapeBase(type 6) → Shape(type 7) → Text(type 2)`.
  Every component is an inclusive-length `ObjectHeader` frame; Shape's decoded
  `flex_offset` lands directly on `text_core::Common`, eliminating the scan for
  the main title/body and page text-box frames. The fixed Shape prefix is now
  decoded as `shape_type`, `original_rect`, `original_angle`, optional path and
  control points; its flex bits gate Common, `ellipsis_type` and
  `text_auto_fit_type`. Text's flex bits gate border colour/width/type. The
  rotated text-box 20-byte prefix delta is ObjectBase `angle` (4) + `pivot`
  (2×f64); the former 48-byte post-Common residue is one auto-fit byte + a
  15-byte Text frame + a trailing 32-byte hash-like value (not sha256 of the
  preceding object). `parse_text_wrapper`, `sdocx_text_wrapper.ksy` and
  `validate_text_wrapper.py` agree on **72/72 wrappers** (56 note title/body +
  16 page text boxes), zero mismatches. `sdocx_note.ksy` now embeds the wrapper
  type directly instead of retaining opaque title/body blobs.
- **Shape/Text wrapper PORTED TO RUST CORE (NEW, 2026-07-12):** the four-frame
  wrapper now lives in `crates/sdocx/src/note_doc.rs` (`parse_object_frame_header`
  + `parse_text_wrapper`), a byte-for-byte port of pysdocx. Both Rust entry
  points were rewritten off the marker/TLV scan onto the structural chain:
  `container::parse_note_text` (note body typed text via `note_body_rich_text`)
  and `page::parse_text_box_object` (page text boxes via `text_wrapper_rich_text`),
  each reaching `text_core::Common` through Shape's flex offset and projecting its
  spans to `RichTextRun`/`ColorRun`/`FontSizeRun` (shared `common_frame_rich_text`,
  the port of pysdocx `_text_box_rich_text`); the legacy scan is kept only as a
  defensive fallback. New parity gate `note_doc::wrapper_parity` + fixture
  `tests/fixtures/text_wrapper_pysdocx.json` (regen `gen_text_wrapper.py`) asserts
  the Rust wrapper matches pysdocx field-for-field on **70 wrappers** (54 note
  title/body + 16 page boxes; the 1 personal `Appunti vari` sample is excluded
  from the committed fixture → 72 locally with it). Note body typed text verified
  byte-exact vs pysdocx end-to-end (`OnlyTextTypeWritten`: 682 chars,
  runs/colors/font-sizes identical). All green (cargo workspace + clippy
  `--all-targets -D warnings` + pysdocx 23/23 + `text_boxes.rs` still 16/16).
  Uncommitted.
- **Typed-text pagination ported to OpenSdocx (UPDATED, 2026-07-13):** the document
  -level typed note body was being dumped entirely on page 0 (running off the
  bottom, never reaching pages 2+). Ported pysdocx `paginate_typed_text` /
  `_paginate_segments` to the app: the note body is now attached to every page
  from its first otherwise-empty physical page, with an anchor-relative band
  `slot` + uniform `band_height` (anchor-page height) in
  the Scene (`ScenePaginate` on `SceneText`, [`lib.rs`](./opensdocx/src-tauri/src/lib.rs)),
  and the worker lays out the whole flow, splits it into page-height bands, and
  draws only its own band ([`render.worker.ts`](./opensdocx/src/render.worker.ts)
  `layoutRichText` + `paginateLines`). `Allsamsungnotes` is the placement
  regression gate: its typed body anchors on physical page 5, not over the
  handwriting on page 1. Oracle match on `OnlyTextTypeWritten`: 2 bands
  (21 lines pg0, 11 lines pg1, pg2 empty).
- **Typed-text placement bug RESOLVED (2026-07-13):** re-investigated against
  the GT photos (`samples/OnlyTextTypeWritten_260701_180427_gt`) with a pixel
  measurement script (row-darkness bands vs the predicted layout, scaled by the
  photo/page ratio). Finding: **pysdocx's line positions were already correct**
  — the "pysdocx is likely wrong too" note above was an unverified guess; the
  ~1-15px residuals measured are consistent with phone-photo perspective noise,
  not a layout bug. The REAL bug was structural and Rust-only: `RichTextBox` had
  **no paragraph-level fields at all** — `common_frame_rich_text` in
  `note_doc.rs` projected only spans (bold/italic/color/font-size) and silently
  dropped the Common frame's `paragraphs` records, so OpenSdocx rendered list
  items with no numbered/bullet/todo marker, ignored center/right alignment and
  left-indent, and gave headings no extra breathing room — all visible on this
  exact sample, none of it present in pysdocx's (correct) render.
  Fix, RE'd bottom-up:
  1. **pysdocx:** `note_doc.common_frame_paragraphs` decodes the structural
     `paragraph_type`/`extra` payload fields (indent/align/line_spacing/list/
     space_before/space_after) into the same dict shape `pysdocx.note`'s legacy
     TLV marker scan already produces — validated **zero-counterexample**
     against the legacy scan on **300/300 paragraphs across all 13 typed-text
     samples** (`tests/test_pysdocx_regressions.py::StructuralParagraphRegressionTest`).
     Documented in `docs/format/container/note-note/typed-text.md`. `render.py`
     itself is untouched (still the legacy scan — already GT-correct).
  2. **Rust core:** `note_doc.rs`'s `parse_common_frame` now retains paragraph
     records (`FrameParagraph`) instead of discarding their bytes;
     `structural_paragraphs` is a byte-for-byte port of the pysdocx decoder;
     new public types `ParagraphInfo`/`Alignment`/`ParagraphStyle`/`ListItem`
     on `types.rs`; `RichTextBox` gained `paragraphs: Vec<ParagraphInfo>`,
     threaded through `common_frame_rich_text`/`wrapper_rich_text_box`. Gated
     by extending the existing `wrapper_parity` fixture/test
     (`text_wrapper_pysdocx.json` now carries each wrapper's decoded
     paragraphs; `assert_paragraphs` checks every field against pysdocx).
  3. **OpenSdocx app:** `build_scene_text` (`lib.rs`) now computes, per
     paragraph: `lead_gap`/`trail_gap` (space_before/after, folded around the
     paragraph's rows so the worker's single running `y` stays exact),
     `x_offset`/`max_width` (indent), `align`, and a `prefix` (list/todo
     marker, sized at the paragraph's own font, checked-todo forcing
     strikethrough + gray). `render.worker.ts`'s `layoutRichText` applies them
     in pysdocx's exact order (indent → prefix measured/reserved → alignment
     checked only when the paragraph fits unwrapped → wrap loop unchanged) —
     pagination's fit check still uses each row's own `advance` alone, matching
     pysdocx `_paginate_segments`. New Rust test
     `typed_note_body_scene_resolves_paragraphs` asserts numbered/bullet/todo
     prefixes, center/right alignment, indent offsets, and heading spacing
     survive into the Scene for this exact sample.
  **Follow-up worker fix (2026-07-13):** the first cut had a bug in the TS
  worker (`render.worker.ts` `layoutRichText`) only, NOT in pysdocx or the Rust
  core: after `y += line.lead_gap` it failed to refresh `rowY`, so a
  paragraph's first visual row — and the pagination fit check that reads its y
  — was short by that paragraph's own `space_before`. On `OnlyTextTypeWritten`
  this dropped `questo è heading 2` (space_before 98px) from y-bottom 2241.4
  back under the 2222 page-break threshold, keeping it on page 1 instead of
  page 2 (GT: page 2). The Python "mirror" used to verify the port computed the
  ideal y-flow and so missed it; the Rust unit test only checks the SceneText
  data, not the worker's layout. Fix: set `rowY = y` right after the `lead_gap`
  bump (every later y bump already refreshed it). Reconfirmed heading 2 →
  page 2. NOTE the break margin is only ~19px, a coincidence of the heuristic
  line-height constants, so pagination is not robust to content edits — a
  proper Samsung line-height model is still future work.
  **AllSamsung structural projection fix (2026-07-13):** the app-specific
  failure was upstream of layout. Rust forwarded Common's raw leading 119
  newlines + U+FFFC table anchor, while pysdocx strips that document-flow
  padding and rebases character/paragraph coordinates; this produced `[OBJ]`
  and pushed the visible body down. `common_frame_rich_text` now performs the
  same coordinate-safe projection. Type-20 strikethrough is also decoded as
  `u8 enabled + 3 residue bytes` (AllSamsung's on/off pair is
  `01 77 00 00` / `00 0c 1f 77`), rather than treating the whole u32 as a
  boolean and striking every later list. Both facts are app/core regression
  gated. Common section pairs were promoted in both text-wrapper/table `.ksy`
  files to contiguous `(text_start, text_length)` ranges; their physical-page
  mapping remains open because Mathsolver is a counterexample to section index
  == page index. Page anchoring therefore remains the explicitly documented
  first-empty-page heuristic.
  All green: `cargo test`/`clippy --all-targets -D warnings` workspace-wide +
  opensdocx (9/9 incl. the new test) + `tsc --noEmit` + pysdocx unittest
  (24/24 incl. the new regression test). Two **pre-existing** opensdocx clippy
  failures (`manual_clamp` in `text_box_layout`, `items_after_test_module`)
  were confirmed via `git stash` to predate this round — not introduced here,
  left unfixed (out of scope). Uncommitted.

## Where we are

- **Math Solver + Web inline sample (NEW, 2026-07-11):**
  `Mathsolver&Hyperlink` closes the Web-object request: link previews are
  `text_core::Common` inline objects of type 13 (not page-layer objects),
  anchored by U+FFFC and backed by an `@web_*.jpg` thumbnail. Its hyperlink is
  therefore not span type 9. The full 766-byte Web body is now decoded as an
  ObjectBase frame plus a type-13 flex frame (thumbnail id, preview body,
  title, URI, image type, version, view type), with a new bit-7 29-byte value
  bounded but honestly opaque. Python + dedicated Kaitai spec/validator agree
  byte-for-byte on the sole Web object. Math Solver does not emit formula span 23; it
  instead adds variable-sized `0x20` named properties associated with the
  recognised strokes (exact relationship Marker).
  `04 01 00 + RecogUIFeature_MathStrokeUuidStringArray` carries a counted array
  of UTF-16 stroke UUIDs. Python + Kaitai now decode these alongside the legacy
  32-byte scalar `extra_key_stroke_shape` form. The `06/07` multi-property
  chains are now decoded byte-exactly: optional UTF-16 recognised expression,
  fail-code property (`7` in every observed chain), then the stroke UUID array.
  The meaning of fail code 7 remains Unknown. HDR_EXT remains dimension-clean.

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

- **Byte-exact table parser ported to Rust core (NEW, 2026-07-11):** the whole
  structural decode now lives in `crates/sdocx/src/note_doc.rs` — a bounded LE
  cursor, `parse_common_frame`/`find_common_frames`, the `note.note` header
  (body blob + `format_version`), and `parse_table_object` with its
  wrap/midpoints/path/outline/borders helpers, all byte-for-byte from
  `pysdocx/note_doc.py`. Exposes new public types `NoteTable` / `NoteTableCell`
  / `TableBorder` / `TableCellSpan` on `metadata.note_tables` (authoritative;
  the legacy clustered-anchor `parse_tables`/`Table` stays as a corroborator).
  Parity-gated by `crates/sdocx/tests/note_tables.rs` against a pysdocx-generated
  fixture (`tests/fixtures/note_tables_pysdocx.json`, regen with
  `gen_note_tables.py`): **20/20 tables, 260 cells** match pysdocx
  `note_doc_tables` field-for-field (geometry, fills, borders, per-cell frame
  text). **`table_index` is really the 0-based HOST PAGE index** (RE finding
  this round): note.note's long-missing table→page reference. Proof — the
  single-table `Allsamsungnotes` note carries `3` and its table's ground-truth
  page is page 4 (index 3; an ordinal would be 0); the styled family increments
  one-per-page; the two `v2` tables that share a page both carry `10`; it equals
  the stacked-Y multiplier `page_index × page_height`. Zero
  `table_index ≥ page_count` in the corpus. Documented in
  `docs/format/container/note-note/tables.md` (the decode-layer field keeps the
  `table_index` name; the render/placement layer treats it as page index via
  `NoteTable::page_index()` / pysdocx `table_index_is_page_index`).
- **Structural tables now RENDER in OpenSdocx + pysdocx (render migration DONE,
  2026-07-11):** both render paths migrated off the legacy clustered-anchor
  `parse_tables` onto `note_doc_tables`. New pysdocx helpers (`note_doc.py`):
  `note_table_grid` (page-local grid from wrap bbox + col_widths/row heights —
  page-local even on geometry-edited tables, unlike cell bboxes) and
  `table_cell_style` (whole-cell char style from the frame spans: 5 bold /
  6 italic / 7 underline / 20 strikethrough / 1 fg color / 3 font_size).
  `render.py` `render_table` now draws per-cell background fills + strikethrough
  and each table lands on its own `page_index` (no more "pagina N"/page-4 guess).
  Mirrored in Rust: `NoteTableCell::whole_cell_style()` + `NoteTable::grid()` in
  the `sdocx` crate; OpenSdocx `build_scene_table(&NoteTable)` + worker draw
  fills/strike; placement in `get_page_scene` filters `note_tables` by
  `page_index()`. **This fixes "no tables visible in OpenSdocx":** the legacy
  scan returned nothing on the styled samples (overfit allowlist), so they never
  showed. Verified: pysdocx renders Allsamsungnotes table on page 4, and the v2
  styled family byte-for-byte against the user's handwritten annotations (blue
  fill column / size-20 column / bold column / struck last row / blue third row).
  Suites green: sdocx + opensdocx cargo (8/8, `page_index()==3`), TS typecheck,
  clippy, pysdocx unittest 22/22.

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
`docs/format/container/note-note/tail-records.md`. The Text/Shape wrapper around
the `text_core::Common` frames is now decoded and embedded in Kaitai; type-22
tables remain dedicated nested specs because they live inside Common inline
object bodies.

## Next tasks

- **`.spi` / Maetel raster codec — DECODED END-TO-END in Python (2026-07-26):**
  `.spi` is Samsung's proprietary raster, used both for page thumbnails and for
  **real page objects** — notably the "convert to math" formula render on page 3
  of `MultiMath_260724_201808` (`media/2@84bbec22-….spi`, 1408×286). Without a
  decoder that page cannot be rendered. Full write-up in the gitignored
  `apk-re/findings.md` ("SPI / Maetel" section); tools in `apk-re/scripts/`.
  State:
  * **Three oracles now exist and are verified.** (1) `ground_truth.pdf` p.3
    embeds Samsung's *own* decode as `1408×286 rgb` + smask — free ground-truth
    pixels, no device (`spi_ground_truth.py`). (2) `spi_emu.py` runs
    `libSPenBase.so` under **Unicorn** on the PC and decodes all 6 `.spi` members
    of the sample; on the formula it matches the PDF on every fully opaque
    pixel (the 0.61% that differ have partial/zero alpha and delta ≤ 2 — the
    premultiplied→straight rounding of the PDF export). (3) `spi_emu.py
    --trace-csv` yields a **ground-truth per-tile trace** (3168 rows = 88×18×2
    planes) of mode + exact bit positions.
  * Decoder shape decoded: `FUN_001c0124` dispatches `[plane*6 + mode]` through
    three pointer tables (regenerated from the `.so` by `spi_tables.py`, not
    transcribed); exactly **2 planes × 6 modes**; `color_index=4` ⇒ 3 colour
    components + alpha; planes are sequential within a chunk with a byte-align
    rewind between passes.
  * `spi_probe.py` is now falsifiable: hard chunk-boundary asserts, an
    illegal-mode oracle (modes 2/4 cannot occur on plane 1), and
    `--verify-handlers` which checks each ported handler in isolation against
    the native trace. **Modes 0 and 1 are EXACT on both planes: 2501/3168 tiles.**
  * **Triage done (2026-07-26), and it resized the job by an order of magnitude.**
    Do **not** measure this work in KB of Ghidra pseudo-C: NEON expands hugely, so
    `FUN_001cf238` is 65 KB of `.c` but only **3596 bytes of machine code**. The
    right metric comes from `.eh_frame` FDEs (`spi_tables.FunctionMap`). The whole
    decoder call graph is **56 functions / 53.9 KB of ARM64**, of which 19.2 KB is
    never executed on this sample. `spi_emu.py --triage` measures the rest
    directly — a block hook for coverage, plus a write hook on the bit-reader
    struct, since consuming bits without touching it is impossible. Net:
    **10 functions / 18.3 KB still to port for bit-exact parsing.** The same hook
    found `FUN_001c2624`, the bitstream refill primitive, reachable *only* via a
    function pointer in `bitreader+0x28` — no static call-graph walk could see it
    (it needs no porting: an ordinary bit reader covers it).
  * **Tree A is DONE (2026-07-26): 2501 -> 2841/3168 tiles bit-exact.** Plane 0
    modes 2 and 4, 340 tiles, all EXACT on the first run after reading the code.
    `FUN_001d3b4c` turned out to be a run-length + Exp-Golomb symbol coder (not a
    NEON monster), and mode 4 is an incremental-palette path. Full grammar in
    `apk-re/findings.md`, "L'albero A decodificato". Two things made it cheap and
    are worth reusing on tree B: `spi_emu.py --element-trace` samples the bit
    position at every call into an inner decoder, so a port is diffed stage by
    stage rather than on the tile total; and the per-tile trace now carries the
    decoder state the handlers branch on (`tile[0x9c4]` palette entries,
    `tile[0x9c8]` index width), without which a handler verified in isolation
    cannot know how much palette was already transmitted.
  * **Tree B is DONE (2026-07-26): layer 2 is CLOSED at 3168/3168 tiles.** Plane
    1 mode 3, 327 tiles. The 11.9 KB estimate was again too high: `FUN_001d0044`
    is 8.3 KB but reads *one bit per tile* before delegating, so the real core
    was 3.1 KB (`FUN_001d2874` + `FUN_001d4000` + `FUN_001d3980`). Grammar in
    `apk-re/findings.md`, "L'albero B decodificato". Two reusable lessons:
    (a) the six lookup tables are **read from the .so** at runtime
    (`spi_tables.load_coefficient_tables`) rather than transcribed — a typo
    would surface as a plausible-but-wrong bit count deep in the corpus;
    (b) `FUN_001d4000` depends on *spatial* neighbour context that only pixel
    reconstruction maintains, solved by observing it instead of deriving it
    (`spi_emu.py --context-trace` reads the two bytes out of emulated memory,
    and `spi_probe.py --context-csv` feeds them back). That oracle stays useful
    for layer 3.
  * **Layer 3 STARTED (2026-07-26), not finished.** Two milestones landed. First,
    the **whole stream now parses sequentially**: `spi_probe.py` walks it end to
    end and all 4 chunks land exactly on 13869 / 32258 / 46864 / 54329. Getting
    there needed a real find — mode 4's palette state (`tile[0x9c4]`/`[0x9c8]`)
    is an *output* of one tile and an *input* of the next, so the walk desynced
    at tile 10 even though every handler was individually bit-exact. Only an
    end-to-end walk could have surfaced that. Second, `spi_emu.py --block-trace`
    captures the four 16x16 blocks before each blit, and mode 4's palette
    expansion reconstructs **313/313 tiles exactly** against it.
  * The NEON worry was misplaced: the only vector instructions in the decoder are
    20 `a64_TBL` inside `FUN_001cf238`, and they are a byte shuffle plus
    `-(x & 1) ^ x` (permutation + zigzag). Everything else in reconstruction is
    scalar. Ghidra's ~760-line expansion was the whole illusion.
  * **Mode 2 blocks: negative result, worth not repeating.** The `a64_TBL`
    sequence is decoded (four shuffles widening 16 bytes into 32-bit lanes,
    `(s >> 1) ^ -(s & 1)`, then a regather whose net permutation is the
    *identity*). But no linear DPCM reproduces the native blocks: straight
    vertical accumulation gives 0/27 tiles, all six symbol-block-to-component
    assignments give 0/27, and shifting the predictor by -1/0/+1/+2 still leaves
    20% of residuals above +-8 where a correct DPCM would leave ~0%. So the
    prediction is 2D or sub-block structured -- consistent with the TBLs grouping
    bytes four at a time. Deliberately left unimplemented rather than shipped
    wrong.
  * **Mode 3 scoped, and it is bigger than expected.** `FUN_001d5abc` shows the
    alpha plane is a full intra coder, not a table swap: neighbour fetch, a
    `(a*2 + b + c + 2) >> 2` smoothing filter, **directional intra prediction**
    over 17 modes, then dequantisation and an inverse transform that adds the
    residual. Five stages go through *function pointers* in the context, resolved
    by reading them at runtime under the emulator: `ctx+0x598` ->
    `FUN_001c7b0c`, `+0x5a0` -> `FUN_001c7540`, `+0x5d8` -> `FUN_001c64f4`,
    `+0x5e0` -> `FUN_001c6a14`, `+0x608` -> `FUN_001c6d4c` (5.4 KB in total).
    **The static call graph cannot see those** -- the same blind spot that hid
    `FUN_001c2624` -- so the earlier "10.5 KB of reconstruction" estimate was low
    by at least that much. The blitter at `ctx+0x630` still needs resolving the
    same way.
  * **THE FORMULA NOW DECODES IN OUR OWN CODE (2026-07-26).**
    `spi_decode.py --png` renders a legible `a^2 + b^2 = c^2` with no emulator
    involved. Against the ground truth: **RGB 6533/402688 pixels differ (1.6%)**,
    alpha 12.5%. So colour is essentially complete -- the residual 1.6% is the 27
    mode-2 tiles (27 x 256 = 6912 px) plus what the copies propagate -- and every
    remaining difference is alpha, i.e. mode 3.
  * Modes 0 and 1 (2501 tiles) copy a 16x16 region of the running frame rather
    than filling blocks, which is why the frame had to exist first. Mode 0 has no
    coded vector: above when at the left edge, otherwise left (`DAT_0012ed78` =
    `(0,16)`, `DAT_0012ee88` = `(16,0)`) -- **2283/2283 exact**. Mode 1 is still
    partial: `FUN_001cd1b4` writes only `dx` and never `dy`, so `dy` **persists
    from the previous tile**; that carry is unmodelled, and those 218 tiles (7%)
    still take their vector from the native trace.
  * 📖 **Full handoff: `apk-re/SPI-HANDOFF.md`** — self-contained, written so a
    fresh session (or another agent) can pick this up without reading the
    chronological log. Runnable commands, the complete format, what is verified
    with which numbers, the two known gaps, and a "traps" section listing the
    things that cost real time. Start there, not here.
  * **THE DECODER NO LONGER NEEDS ANY ORACLE (2026-07-26).** Both trace
    dependencies are gone, which is what makes a Rust port worth doing rather
    than a kludge. (a) Mode 1's motion: `FUN_001cd1b4` does write `dy`, via
    `*(int *)(param_2 + 0x41b)` -- 0x41b in 8-byte units *is* 0x20d8, which is
    why grepping for "0x20d8" missed it. Gate bit -> `(0,16)`, else
    `dx = zigzag(c1 + 1) * 16`, `dy = expgolomb(c2) * 16`; the `+1` is because
    the native builds `payload + (1 << z)`. **2501/2501 exact.** (b) Mode 3's
    contexts come from a 4-pixel-granularity mode map (`spi_probe.ModeMap`)
    built from decoded modes alone -- no pixels needed. The non-obvious rule:
    **the map does not carry across AA02 chunks** (a chunk restarts the native
    line buffers), worth 126 of 2199 contexts. **2199/2199 exact.**
    `spi_probe.py` now walks all 4 chunks and `spi_decode.py --png` renders the
    formula with no `--context-csv` and no trace files at all.
  * **RUST PORT DONE (2026-07-26).** `crates/sdocx/src/samsung_spi.rs` +
    `crates/sdocx/tests/samsung_spi_decode.rs` (both untracked). The Rust decoder
    produces **byte-identical RGBA** to the Python reference. Static tables are
    Rust `const`s -- no `libSPenBase.so` read at runtime, no Samsung binary in
    the repo. Three parity gates, all of which actually run here: chunk
    boundaries (needs only the sample), 3168/3168 per-tile bit counts, 313/313
    mode-4 blocks. Mode 2 and mode 3 *reconstruction* remain honest gaps --
    parsing is complete, so the stream stays in sync. Detail in
    `apk-re/SPI-HANDOFF.md` §9, including why an earlier Codex attempt looked
    green while shipping a fabricated 256-byte lookup table (**0/27 tiles**
    against the real fixture); it had also contaminated `spi_decode.py`, and both
    are now cleaned.
  * **THE CODEC IS FULLY DECODED (2026-07-26).** `spi_decode.py` reproduces the
    native decoder **exactly**: 667/667 blocks (mode 2 **27/27**, mode 3
    **327/327**, mode 4 313/313) and **0/402688 pixels differ** from
    `multimath_formula_emu.png`. The 2462-pixel (0.61%) gap to the Samsung PDF
    export is the export's own floor — the emulator shows the same number. No
    oracle, no trace files, single pass. Three things closed it, all found by
    diffing against `--intra-trace` rather than transcribing the 20-case switch in
    `FUN_001cbf98`/`FUN_001cc150` (which turned out not to be needed):
    (a) **mode 2** is the scalar `else` branch of `FUN_001cf238` (submode 2), a
    vertical DPCM with **step 4** plus a wrap — the step is exactly why the
    step-1 version had scored 0/27;
    (b) **reference construction** is HEVC's: the two arrays have **independent
    corners**, undecoded samples are *unavailable* and replicate the last
    available value forward (not clamped), and the `[1,2,1]/4` smoothing is
    **conditional** on `min(|angle-5|,|angle-13|) > threshold[dim]` — applying it
    always drops refs to 545/2199;
    (c) the **tile context** rule is symmetric: on the first row of an `AA02`
    chunk the row above does not exist, and the missing side replicates the other
    side's first sample (0x80 when neither exists). That is the whole explanation
    of the "tile 0 has top=0x80, the others have top=0" anomaly.
    Declared Unknowns: the smoothing thresholds have slack (distance 3 at dim 4
    and distance 1 at dim 8 never occur; `dim 16` never occurs), and the
    "only-top-available" context rule is verified on 4 tiles in an all-zero
    region, so it is not distinguishable there from a carried-over line buffer.
  * **PLANE 0 MODE 3 PARSED -- THE WHOLE CORPUS NOW WALKS (2026-07-26).** The one
    remaining unported handler (`FUN_001ce290`) is done, and the `.spi` census
    goes **30/220 -> 220/220** members walked end to end with every `AA 02` chunk
    boundary hit exactly (`apk-re/scripts/spi_corpus_census.py`, which asserts the
    boundary rather than just "no exception"). Why it matters: the `page_*.spi`
    members are **Samsung's own full-resolution render of every page**, one per
    (page, layer) -- ~220 reference images across 25 samples, i.e. a per-page
    rendering oracle the project has never had. Structure: the wrapper reads 1
    bit (the plane 1 wrapper has none), then `FUN_001d0044` loops over **bands**
    -- 3 colour on plane 0, 1 alpha on plane 1 -- reading one bit each: set means
    four 8x8 quadrants, clear means a single unsplit 16x16. Four fixes, all found
    by diffing against the emulator: (a) the 16x16 scan tables were already in the
    binary, `SCAN_SIZE_CLASSES` was just capped at 4; (b) **the mode map is per
    band**, not per plane (the context trace has a `band` column we were ignoring),
    and a 16x16 block writes 4x4 cells not 2x2; (c) **`quant = 23` on the colour
    bands**, 0 on alpha, which picks which half of the sub-block mask table a 4x4
    block reads -- 122 of the 150 residual failures; (d) **chunks are chained by
    their own length** (the u32 after the `AA 02` tag), and scanning for the tag
    bytes is unsafe -- one member had a false positive 7257 bytes early that passed
    both existing validity checks. Also **removed a wrong invariant**: the
    "coefficient position past the scan" guard fires on legitimate data (tile 809
    of page-59 reaches 321 on a 256-entry scan) while bit consumption stays exact.
    Declared Unknown: all 220 members carry the same chunk header, so the corpus
    cannot tell `quant = 23` from a header field (`field_04`) versus a hardcoded
    constant.
  * **PLANE 0 MODE 3 RECONSTRUCTION: ESSENTIALLY DONE (2026-07-27).** The
    missing link, `FUN_001d5f44`, is transcribed and exact: **129/129** calls on
    basic-18 and **27/27** on page-59, verified per call against the int16 plane
    the native produces. The colour stage (`FUN_001c1d3c`) is a reversible
    YCoCg-R-style lifting with chroma biased by `+0x100` -- at zero chroma it
    yields R=G=B, which is exactly the flat grey that made the old attempt look
    absurd -- and reproduces **9984/9984** pixels. Dequantisation, whose formulas
    were documented but whose code was never in the repo, is now in
    `spi_decode.dequant()` at **61/61** (plus 61/61 inverse transforms). End to
    end: basic-18 **3485/3619200 pixels differ (0.10%)**, page-59 **883 (0.02%)**,
    and the MultiMath formula stays at **0/402688**; corpus 220/220; repo suite 35
    tests OK. Three things had to be fixed before any of it could be measured, all
    documented in `apk-re/SPI-HANDOFF.md` 7.3:
    (a) two claims in the handoff were **wrong** -- `FUN_001d31b8` is called with
    literal zeros here, so the coefficient buffer is `tile+0x140` for every band,
    and the "known tracer bug" was therefore not a bug;
    (b) the real fixture defect was that the reference arrays were captured at
    **34 bytes instead of 0x42** (33 int16), so the 16x16 blocks -- 113 rows of
    129 -- were compared against half a reference. That, not the other three
    leads, is why the first attempt scored 0/119;
    (c) the four unresolved context slots were read at runtime: `ctx+0x610` is
    the planar predictor **we already had**, `ctx+0x618` is the alpha's angular
    predictor in int16 with the same tables, `ctx+0x620` is the residual add
    (nine parameters, the ninth passed **on the stack**, which is why Ghidra shows
    eight at the call site), `ctx+0x628` is dead here.
    Also settled: the smoothing decision is a plain **table lookup**
    (`UNK_00131ace[size_class][mode]`), not the mid-point thresholds that were
    previously declared Unknown -- the table was already extracted, `spi_decode`
    just was not using it.
  * **The run/level escape gap is CLOSED (2026-07-27).** There are **two**
    coefficient decoders and the quant picks which: in `FUN_001d2874`,
    `*(char *)(param_1 + 7)` is `tile[0x38]` in 8-byte units -- the same trap for
    the third time -- and it is 0 on the alpha but 23/24 on plane 0, so plane 0
    goes through `FUN_001d42a8` instead of the inline loop. The two share their
    bit syntax exactly, which is why bit counts stayed exact while reconstruction
    was wrong; only the escape branch differs (bias `value-1` not `value-0x80`, a
    fixed 8-bit run field, level **minus** one) plus scan context 0 always.
    Pre-dequant buffers went 37/61 -> **61/61**, and the scan overrun to 638
    vanished (max position 255) -- it was an artefact of the wrong formula, and
    the "native reads past the end of the scan" idea is falsified.
  * **Two more findings, from a third sample.** basic-18 and page-59 both hit
    **0 pixels**, but `Allsamsungnotes media/11@page_0000007` -- 4139 coefficient
    blocks against basic-18's 113 -- did not, which is exactly why it was worth
    generating a third reference. It exposed:
    (a) **the quant is not a constant**: the chunk header carries **two** quant
    fields, `(field_03, field_04) = (24, 23)` on every corpus member, and the bit
    `FUN_001ce290` reads -- whose meaning had never been determined -- selects
    between them **per tile** (bit 0 -> field_03, bit 1 -> field_04). Verified
    **1409/1409** tiles against the native `tile[0x3a]`. No gate had caught it
    because `quant_group[23] == quant_group[24]`, so the quant does not change
    parsing at all;
    (b) **the clamp width is per band** -- luma 8 bits, chroma 9 -- read out of
    the native (the ninth argument of `FUN_001c6ea4`, passed on the stack).
    Chroma is biased by `+0x100` and legitimately exceeds 255; neither of the
    first two samples saturates, so they could not tell 8 from 9.
  * **Sub-block references TRANSCRIBED, and a channel order fixed (2026-07-27).**
    `FUN_001cc318` (4x4) and `FUN_001cc4dc` (8x8) are position switches, not a
    substitution rule: some cases **do not write the whole array**, so the tail
    keeps the previous sub-block's values -- the arrays are locals of
    `FUN_001d5f44`, zeroed only on entry and reused across the loop. Transcribed
    literally, prediction goes **4489/4491 -> 4491/4491** on the hard sample and
    stays 129/129 and 27/27 on the other two. Then a second finding: the frame
    planes are **G, R, B**, not R, G, B. Every path writes the same three planes,
    but the first three reference samples are **entirely monochrome** (R == G == B
    on all 7.6M pixels), so they could not tell any permutation apart; the
    coloured sample has 144661 pixels with R != G and pins it. Swapping the first
    two planes took that sample from 4.0% to **205 pixels** with the other three
    unchanged at 0.
  * **A fifth reference, chosen to falsify.** `ImagesAllTrasnsformations
    media/2@page_0000130.spi` (449 KB, imported photos) exercises 3975 plane-0
    mode-3 calls, all three block dims (so the newly transcribed reference
    switches run 612 times), **both quants**, **262464 pixels with R != G** and
    2.78M non-opaque pixels -- and lands at **0/3619200**. That is the
    independent confirmation the three monochrome samples structurally could not
    give. A corpus-wide parameter census also came back uniform: `color_index = 4`
    on **220/220** members and `(field_03, field_04) = (24, 23)` on **880/880**
    chunks, so no untested format variant exists in the corpus.
  * ✅ **THE CODEC IS BIT-EXACT ON THE WHOLE CORPUS (2026-07-27).**
    `apk-re/scripts/spi_corpus_pixels.py` decodes every `.spi` member twice in one
    process -- `libSPenBase.so` under Unicorn and our decoder -- and compares in
    memory: **220/220 members identical, 28 archives, 800,698,496 pixels, 0
    differences, 0 failures** (13 min on 6 processes). This is no longer "the
    samples we have pass": it is the corpus. Sanity-checked first -- flipping one
    byte of our output makes it report exactly 1 differing pixel.
  * Six of those members are the named references, all at **0 pixels**: formula
    0/402688, basic-18 0/3619200, page-59 0/3619200, ImagesAllTrasnsformations
    page 130 0/3619200, Allsamsungnotes page 7 **0**/3619200 (was 205), and the
    new `Machine_learning… media/193@page_0000177.spi` **0**/3616000. Against the
    Samsung **PDF export** -- evidence independent of the emulator -- the formula
    lands on 2462/402688, which is the emulator's own floor. Per-call gates:
    plane 0 129/129 + 27/27 + 4491/4491, dequant/transforms 122/122, and the new
    **alpha gate 4374/4374 tile contexts + 33210/33210** references, predictions
    and outputs. Parsing unchanged: 3168/3168 bit counts, corpus 220/220, repo
    suite 35 OK.
  * **Closing the 205 pixels took three defects, not one** -- full write-up in
    `apk-re/SPI-HANDOFF.md` §7.2/§7.3:
    (a) the **smoothing corner came from `top[0]` instead of `left[0]`**
    (`FUN_001d5abc` line 163, same formula the colour planes already used). The
    two only differ on the first tile row of an `AA02` chunk, where `left[0]` is
    0x80 and `top[0]` replicates `left[1]` -- exactly the 5 failing tiles. One
    line, 205 -> 0;
    (b) the **alpha sub-block reference switches had to be transcribed** after
    all (`FUN_001cbf98` / `FUN_001cc150`), the same lesson as the plane 0 twins:
    the arrays are locals of `FUN_001d5abc` zeroed only on entry, so entries a
    case does not write stay **stale**. The generic model sat at 2168/2199 on the
    formula *without changing a single block*, which is why it had been declared
    unnecessary -- on ml177 it got 740/26626 references wrong;
    (c) **mode 5 (raw blocks) was parsed but never reconstructed**: `spi_decode`
    threw away the 3x256 raw bytes `spi_probe` already returned, so those tiles
    came out black and the error spread to neighbours through the context. 13
    tiles in the whole corpus, none in the first five references.
  * ✅ **The decoder now lives in the repo (2026-07-27):** `pysdocx/spi/`
    (`parse.py`, `decode.py`, generated `tables.py`), a `pysdocx spi` CLI
    subcommand, and `tests/test_spi_decode.py` pinning the 18 `.spi` members of
    the *tracked* samples by SHA-256 of their decoded pixels (regen:
    `python -m tests.regen_spi_golden`). Those hashes come from decodes that had
    just been proven identical to the native decoder, so the gate carries the
    emulator-verified truth into the repo **without** carrying the APK: no
    Samsung bytes are vendored and nothing reads `libSPenBase.so` at runtime --
    its static tables were extracted once, offline, by
    `apk-re/scripts/spi_gen_tables.py`, each with its Ghidra provenance. The
    oracle side (emulator, tracers, ~50 MB of captured fixtures, decompiled
    sources) stays in the gitignored `apk-re/`, and now imports the tracked
    decoder instead of keeping its own copy -- one source of truth. Rationale and
    the new repo/no-repo line: `apk-re/SPI-HANDOFF.md` §10.
  * **The method that found them, worth reusing:** a new gate
    `apk-re/scripts/spi_verify_intra.py` drives the *real* `spi_decode` code
    (through new `context_tap`/`subblock_tap` hooks) and compares it against
    `--intra-trace` **in cascade** -- tile context, then references, prediction,
    output. The first stage that diverges is the defect; everything after it is a
    consequence. On the 5 failing tiles it said immediately: context correct,
    references wrong, and only in the corner. It also prints how many tiles are in
    the risky configuration, so a sample that "passes" without exercising the
    branch is visible as such -- the formula has 80 exposed tiles and passed at 0
    pixels **with the wrong corner**.
  * **The severe alpha sample now exists**, and was added to falsify rather than
    confirm: ml177 has **190** exposed tiles (the corpus maximum) and 26626 intra
    calls. It caught (b) and (c) after (a) had already taken allnotes7 to zero.
  * ⚠️ **Still falsified, do not repeat:** letting the pixel context cross the
    chunk boundary (`top_available = py > 0`) makes it worse (205 -> 9382) **and
    breaks the formula** (0 -> 1880); doing it only on the alpha is worse still on
    all three samples. The per-chunk reset is right for both planes.
  * (superseded) **Was open:** the 4x4 sub-block reference
    arrays have a **stale tail**. `FUN_001cc318` case 3 writes only `top[0..4]`;
    `top[5..8]` keep whatever the previous sub-block left, because the arrays are
    locals of `FUN_001d5f44` zeroed only at function entry and reused across the
    loop. Mode 5 (angle 7, step 13) really does read `top[5..6]`. The generic HEVC
    substitution model is therefore wrong here even though it sufficed on the
    alpha; closing it means transcribing `FUN_001cc318`'s 20 cases and
    `FUN_001cc4dc`'s 4 literally, with persistent arrays. Current numbers on that
    sample: pre-dequant **2060/2060**, dequant **1474/1474**, flags **5112/5112**,
    prediction **4489/4491**, references **4076/4227**, image **4.7%**.
  * (superseded) **Was open: the run/level escape on size class 4.** On 11 of
    basic-18's 61 coefficient blocks the decoded pairs disagree with the native
    buffer in a specific shape -- our level is consistently one larger in
    magnitude, and the run is far too big, so the running position overruns the
    scan (up to 638 on a 256-entry order). Neither changes the bit count, which is
    why 220/220 still parse exactly: this is a gap the parsing gate structurally
    cannot see. **Falsified, do not repeat:** "the native reads past the end of
    the scan" -- the scan orders are consecutive in memory, so an overrun lands in
    the next table and collides, while the native buffer holds exactly one
    non-zero per coefficient. All 3485 differing pixels sit inside the 15 affected
    tiles; nothing propagates.
  * (superseded, kept for the trail) **Was open: plane 0 mode 3 *reconstruction*.** `FUN_001d31b8` (472 B)
    replaces `FUN_001d5abc` as the plane 0 driver. Feeding the existing intra
    chain with plane 0 coefficients gives wrong blocks: where the native emits a
    flat grey (R=G=B ~ 0x25) we emit scattered 1..9. Two concrete leads -- the
    native output being R=G=B says the three bands are luma + two chromas with a
    final conversion, and the 4-9x magnitude gap plus `quant = 23` (vs 0 on alpha)
    says a **dequantisation** step that was the identity on plane 1 is missing.
  * **Plane 0 mode 3 reconstruction: dequantisation DONE (61/61), inverse
    transform identified but not implemented (2026-07-26).** `FUN_001d31b8` is a
    118-instruction dispatcher that calls two function pointers per sub-block --
    a dequantiser then an inverse transform, both in place on the coefficient
    buffer. All six resolved at runtime (3 dequant + 3 transforms, ~3.7 KB).
    **Dequant is closed**: tables extracted into `spi_tables.load_dequant_tables`
    (the `quant -> (matrix<<4)|shift` table has exactly 52 entries, matching the
    `quant > 0x33` bound already in the parser; `quant = 23` -> matrix 5, shift 3),
    formulas verified 61/61 against `--recon0-trace`, a new oracle that captures
    each primitive's buffer before and after.
    **The transform is H.264's integer transform** -- proven two ways: impulse
    probing gives exactly the `[64,64,64,64 / 64,32,-32,-64 / 64,-64,-64,64 /
    32,-64,64,-32]` basis, and the disassembly is the H.264 inverse butterfly with
    a final `(v + 0x20) >> 6`. New reusable tool for that:
    `apk-re/scripts/spi_probe_native.py` **calls native primitives directly under
    Unicorn with synthetic input**, turning the emulator into an unlimited oracle
    instead of relying on whatever the corpus happens to contain.
    **The placement stage is now located too, and the call graph is closed.** It
    was not in the parse handler but in the **reconstruct** table
    (`PTR_FUN_00204300`), never looked at: `(plane 0, mode 3) -> FUN_001c1d3c`,
    **1072 B** (the plane 1 entry is only 188 B because its work lives inside
    `FUN_001d5abc`). Its 14 indirect calls all go to just two functions --
    `ctx+0x630 -> FUN_001c3850` (256 B, a plain unrolled 16x16 `ldr q0`/`str q0`
    blit with source/dest strides) and `ctx+0x5e8 -> FUN_001c3db8` (424 B, the 8x8
    chroma equivalent). Their argument widths, 16 from `tile[0x20e0]` and 8 from
    `tile[0x20e8]`, independently confirm that **plane 0 is a YCbCr 4:2:0 coder**
    -- consistent with the native emitting R=G=B when chroma is zero, and with
    bands 1 and 2 almost never carrying coefficients. Since the two primitives are
    plain copies, prediction, residual add and colour conversion are all inline in
    those 1072 bytes. Proof a prediction exists at all: on tile 511 of basic-18 the
    residual is +/-7 noise while the native block has real shape (~37 at the
    bottom, 0 above) and `native - residual` is not constant.
    **Honest total still missing: 4564 B** -- 2812 of inverse transforms
    (mechanical transcription, verifiable in one shot with the probe), 1072 of the
    placement dispatcher (the real remaining RE), 680 of blits (one already read
    and trivial). For scale, the alpha chain already finished was ~4.2 KB.
  * **THE THREE INVERSE TRANSFORMS ARE DONE (2026-07-26), 61/61 on real calls.**
    What unlocked them: all six remaining functions turned out to be **already
    decompiled to C** in `apk-re/decompiled/libSPenBase/`, so this was
    transcription from readable C, not from interleaved assembly. And the C shows
    the one thing no fitting could guess -- **every intermediate is truncated to
    `short`, at every single step**, with logical shifts on sign-extended ints.
    4x4 and 8x8 are H.264-style lifting butterflies; **16x16 is HEVC's integer
    DCT-16**, standard matrix (the probe returns exactly `90 87 80 70 57 43 25 9`,
    `89 75 50 18`, `83 36`, `64`), with the canonical **shift 7 then 12**.
    Verified 300/300 and 460/460 on random vectors plus edge cases, and **61/61 on
    the real calls**. Declared limit: the 16x16 model diverges on *saturated*
    inputs (+/-32767, 42 synthetic cases) because it does not reproduce the NEON
    version's internal overflow; real dequantised data never gets there (35/35).
  * **Step 0 measured, and it resolved an 11816-byte doubt in our favour
    (2026-07-26).** Do **not** trust the triage's "executed?" column: it marks as
    unexecuted functions reached through context pointers that run constantly.
    Counting with a per-address hook (`scratchpad/count_calls.py`) shows
    `FUN_001c8b5c` (11816 B) *does* run -- but it is **the planar predictor we
    already implement**: our `predict` mode-17 formula reproduces it **60/60** at
    dim 4, 8 and 16, so those 11816 bytes are Ghidra unrolling, not new work.
    `FUN_001c3db8` (424) and `FUN_001d75d4` (608) never run at all -> refuse, do
    not guess. Real remaining surface: **8140 B** across 8 functions, the key one
    being `FUN_001d5f44` (1332 B), the plane-0 analogue of `FUN_001d5abc`: it
    reads the residual at `tile+0x140` and the reference context at
    `tile + band*0x42 + 0x3120/0x31e6`, and writes the reconstructed plane to
    `tile[0x3108 + band*8]`, which the colour transform then consumes.
  * **Step 1 started: `FUN_001d5f44`, the plane 0 prediction.** New oracle
    `spi_emu.py --predict0-trace` captures band, dim, `nsub` (`tile[0x947]`),
    mask, modes, both reference buffers and the produced plane
    (`apk-re/fixtures/basic18_predict0.csv`, 129 rows). Established: it reads the
    residual at `tile+0x140` (+ `band*0x200 + sub*0x80`), references at
    `tile + band*0x42 + 0x3120` and `+0x31e6` (34 bytes each), writes
    `tile[0x3108 + band*8]`; it does **not** call `FUN_001d31b8` -- they are
    siblings, 129 calls each, both from `FUN_001d0044`.
    ⚠️ First attempt falsified: reusing the plane 1 `predict` with `a = ref_a`,
    `b = ref_b`, mode from `tile[0x33]` and `clamp(pred + residual)` scores
    **0/119** on unsplit blocks (~150 of 256 positions differ, but magnitudes are
    comparable -- the shape is close, the mapping is not). Leads, in order:
    (1) **known bug in the current trace** -- bands 1 and 2 capture `tile+0x140`
    instead of `tile + band*0x200 + 0x140`; (2) the order between `FUN_001d31b8`
    and `FUN_001d5f44` -- if prediction runs first, the buffer holds raw
    coefficients, not the residual; (3) the mode location may not be `tile[0x33]`
    on plane 0; (4) `ref_a`/`ref_b` may be swapped or offset differently.
  * ⚠️ **Correction to the earlier estimate**: "4564 B, graph closed" counted only
    *indirect* calls. `FUN_001c1d3c` also makes direct ones. The verified full
    graph leaves **5368 B** still to do: `FUN_001c1d3c` 1072, **`FUN_001d6478`
    2692** (it writes `tile+0x2560/0x2580/...`, i.e. it is the plane 0 tile-context
    builder, the analogue of `FUN_001cef0c`, initialising references to 0x80),
    `FUN_001d75d4` 608, `FUN_001c1c00` 316, and the two blits 680. None of those
    call anything further -- that part is now genuinely verified.
    **The open question is still where prediction enters**: who fills
    `tile+0x3108/0x3110/0x3118` (the reconstructed Y/Cb/Cr the colour transform
    reads) from the residual at `tile + band*0x200 + sub*0x80 + 0x140`.
    **What stopped the transforms earlier**: every parametric model plateaus at **52/60** random
    vectors. The internal `>>1`s truncate and the code is full of scattered
    `sxth`, so the exact arithmetic depends on *where* each truncation falls --
    fitting cannot guess that. The honest remaining route is a **literal
    transcription** of the three functions (~90 dataflow instructions for 4x4,
    ~150 and ~400 for 8x8/16x16): mechanical and verifiable in one shot with the
    probe (60/60 or nothing), but transcription rather than deduction. And the
    **placement stage is still unlocated** -- the transform works in place and
    nothing in the dispatcher adds it to a prediction or writes the final 16x16.
    Falsified, do not repeat: pure matrix model without the `>>1` truncations
    (33/40); butterfly with every combination of shifts 0..13, rounding, row/column
    order, 16-bit intermediates and asr-vs-lsr (max 52/60).
    Extending `spi_trace.py --intra-trace` to latch on `FUN_001d31b8` (done, plus
    new `driver`/`arg3` columns -- `arg3` is the band) narrowed it sharply: all
    **362** `FUN_001c6a14` calls on basic-18 come from `d5abc` with band 3, so
    **`FUN_001d31b8` never calls it**. Colour reconstruction is not the intra
    chain with different parameters, it is a separate primitive inside those 472
    bytes. Plane 0 mode 3 is therefore parsed but deliberately **not**
    reconstructed in `spi_decode.py`. Next: read/trace `FUN_001d31b8` itself.
    Working fixtures already generated: `page59_*` and `basic18_*`.
  * **Next: port mode 2 + mode 3 reconstruction to Rust.** `samsung_spi.rs`
    currently has parsing only; the reconstruction stage is what has to be added,
    and the parity gate then becomes a direct comparison against
    `multimath_formula_emu.png`. Note the corpus has only **one** non-thumbnail
    `.spi`, so nothing here can be promoted to `docs/format/` or `spec/ksy/`
    under the zero-counterexample rule — it stays in `apk-re/` until more samples
    exist.
  * Earlier claims now **retracted**: the "1582/1584 tiles, stays in sync" result
    was a false positive (the probe over-consumed ~14% and read only one plane;
    the file contains *no* mode-5 tiles at all), and `FUN_001cf238` is not the
    row-state function but the mode 2/4 payload decoder.

- **Grounded typed-text line-height / pagination model (CORE DONE, residual
  calibration OPEN, 2026-07-13):** the two controlled `.sdocx` + vector-PDF
  exports ground the document-body advance as
  `raw_font_size * (40/9) * line_spacing`, with default spacing 1.35 (therefore
  raw size ×6), and show that an empty paragraph keeps the font carried by its
  newline. Whole line boxes paginate inside the decoded Common top/bottom
  margins (`10 * 40/9` each) and retain a preceding heading gap across a break.
  Python and OpenSdocx now share this model. Page assignments match the exports
  **32/32** for the 11/14/19/64 sample (`[23,6,3]`) and **50/50** for uniform
  size 15 (`[24,24,2]`). The older screenshot GT now has page-1 RMSE 7.91 and
  retains its page-break gap. `Allsamsungnotes` now provides both in-app and
  vector-PDF GT: removing one host-font-only wrap restores all 8 rows (PDF RMSE
  3.60, in-app RMSE 4.74 page units), and grounds separate numbered vs
  bullet/todo hanging columns. Remaining: font-size-dependent glyph anchor /
  baseline metrics, independent validation of each explicit `line_spacing`
  choice, paragraph-style/indent calibration, and the calibrated todo minimum
  row height. Commands and evidence are in `docs/format/heuristics.md`; desired
  follow-ups remain in `docs/format/sample-wishlist.md`.
- **`.page` header preamble — RESOLVED end-to-end as a sequential field-flags
  structure (2026-07-20, supersedes the 2026-07-11 entry below).** Found via
  the same `squ1dd13/sdocx2pdf` cross-reference process already used for
  `note.note`, prompted by the user surfacing a second inkterop/sdocx2pdf
  link. The whole preamble (bytes `0 .. base`) decodes sequentially: fixed
  header (`flex_offset`, property/field-flags bitfields, orientation, dims,
  uuid, timestamps, format version) then a field-flags-gated optional region
  in bit order (`drawn_rect`, `tags`, `template_uri`, background
  id/mode/colour/width/rotation, `pdf_data_items`, `template_type`,
  `canvas_cache_map`, `imported_data_height`, `theme`,
  `recognised_data_modified_time`, `stroke_recognition_data`,
  `custom_objects`). New module `pysdocx/page_header.py`, gate
  `spec/tools/validate_page_header.py`, zero counterexamples on **220/220**
  corpus pages — this fully resolves what the entry below left open (`kind`/
  paper/template presence are just field-flags bits, no signature lookahead
  needed to explain them). Also ported to `spec/ksy/sdocx_page.ksy`
  (field-for-field mirror) + `spec/tools/validate_page.py` +
  `tests/test_kaitai_spec.py::test_page_header`, all green.

  Cross-checked field-for-field against the pre-existing heuristic scanners
  below wherever both fire, zero disagreements: `background_colour`,
  `template_type` id (incl. previously-unnamed ids 10/12-15 — Todo/Custom/
  Weekly/Monthly/Manuscript, Marker naming from sdocx2pdf, not yet
  hand-labeled by us), `template_uri` (structural read is strictly cleaner —
  the heuristic occasionally over-reads one leading UTF-16 code unit).
  `pdf_data_items` also finds a case the heuristic missed entirely:
  `samples/cs61bl_su22` has a **20-entry** tiled/pageless PDF import (not yet
  wired into rendering — separate follow-up). Two things sdocx2pdf's own
  schema doesn't cover, found while validating: sticky notes'
  `skn_bg_color` (never extracted before — a signed-decimal Android ARGB
  string, `"-6482"` == `0xFFFFE64E`, warm cream, on all 3 corpus instances),
  and every sticky-note `custom_objects` entry (3/3) carries an unmodeled
  8-byte trailer (two `u32`s, both `5303`) past where sdocx2pdf's parser
  calls `ensure_eof()`.

  **Two new open items** (see `docs/format/unknowns.md`): (1) sticky notes'
  outer `CustomPageObject.rect` and `custom_data["skn_collapse_rect"]` are
  two *different* bounding boxes on every instance — which is the true
  on-page icon placement needs a targeted sample with an unambiguous visible
  icon (a GT-photo check today was inconclusive, partial scroll capture);
  (2) the `5303`/`5303` trailer's semantics.

  The legacy heuristic scanners (`_locate_paper_record`, `page_template`,
  `page_background_color`, `page_custom_template_uri`, `page_pdf_template`)
  are UNCHANGED for now — deliberately not touched this round since they're
  mirrored in `crates/sdocx/src/page.rs`; swapping their internals to the
  structural read is a separate follow-up (their outputs already agree with
  the structural decode everywhere both fire, so this is a safe, low-urgency
  cleanup, not a correctness fix).

- **`.page` header preamble — field sequence DECODED, `content_bbox` gate DONE,
  template gates OPEN (2026-07-11, superseded above).** the bytes before the paper
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
- **Page text-box `text_core::Common` + wrapper: DONE (2026-07-12).** All 16
  page text boxes parse through the complete ObjectBase/ShapeBase/Shape/Text
  chain; Common is reached from Shape's flex offset (386 non-rotated / 406
  rotated), not scanned. The 20-byte rotated delta is angle+pivot and the
  48-byte tail is auto-fit + Text frame + 32 hash-like bytes. Stored margins
  remain `[8,4,8,4]`. Follow-up is render-only: reconcile the rotated-wrap
  inset heuristic with those decoded margins.
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
  Follow-up (style-tail semantics) is now **DONE** too — see "Table styling
  FULLY decoded + Kaitai-gated" below; the renderer takes grid geometry from
  the structural parse instead of anchor clustering.
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
  and is now the canonical status list. **Same day, later:** the table-
  style-tail sample spec this pointed to was itself closed by the
  `Tabella4x3Regolare` v1+v2 samples — see "Table styling FULLY decoded"
  above and `sample-wishlist.md`'s "CLOSED — Priority B" section. Merged
  cells turned out N/A (no UI action); only minor residual gaps remain
  (left/right vs top/bottom border-pair disambiguation, custom border
  colour/width if the UI ever exposes them) and aren't worth a dedicated
  sample.
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
  **Also ruled out (2026-07-14) via APK static RE** (see `apk-re/`, untracked):
  the entire native save pipeline (`SDoc_save1..4` → `SDocImpl::Save` →
  `SaveWriteCache`/`SDocDocument::WriteFile`/`SDocContent::WriteFile` →
  `SavePrepareZip`/`SaveZip`/`NoteZip::Zip`) was traced call-by-call and
  contains no hash/digest logic; neither do the 3 Java call sites of
  `spenSDoc.save()` in the app's real save path. Paused by user decision, not
  because the trail is exhausted — a live runtime trace would likely resolve
  it quickly since the obvious places are now excluded. Don't redo the native
  trace if picking this back up; start from `apk-re/04-ghidra.md`.

## OpenSdocx viewer UI (app UX)

Frontend is vanilla TS + Vite (no framework): [`index.html`](./opensdocx/index.html)
(toolbar + `#thumbs` panel + `#stage`), [`main.ts`](./opensdocx/src/main.ts) (all
state/layout/zoom/nav/thumbnails), [`styles.css`](./opensdocx/src/styles.css),
[`render.worker.ts`](./opensdocx/src/render.worker.ts) (rasterizer). No backend
changes needed for viewer-UX work.

- **DONE (2026-07-19): Okular-style toolbar + thumbnail sidebar + facing pages.**
  Icon toolbar (inline SVG, CSP-safe) in 3 flex sections (left = file/zoom/view-mode,
  centre = page nav, right = audio/export stubs); zoom combo (typeable % + dropdown
  Fit-width/Fit-page/presets), editable page box, up/down page arrows. Left thumbnail
  panel (`#thumbs`, toggle `#sidebar-btn`), virtualized, click-to-jump, current-page
  highlight. Facing-pages view mode (`viewMode`, row-model `computeLayout` →
  `rows`/`pageLeft`/`pageTop`, continuous two-column scroll; single mode
  byte-identical). Audio + Export are **placeholder buttons only** — behaviour
  deferred (Audio: user to supply a Samsung Notes screenshot + spec; Export: formats
  PDF/image/SVG, client-side from the worker's per-page `ImageBitmap` is the natural
  path, would need a Tauri file-save command + capability entry).

- **DONE (2026-07-19): thumbnail sidebar performance pass — real improvement,
  user not fully satisfied, left open for a future round.** Multi-step session:
  1. **Scroll-lag fix** (options 1+2 from the original TODO): `updateThumbs()`
     no longer evicts off-screen thumb bitmaps (`evictThumb` removed — bitmaps
     are tiny, ~124 KB each, a 66-page doc is ~8 MB total, trivial to keep all),
     and the sidebar's scroll listener is debounced 150 ms
     (`scheduleThumbsOnScroll`) so a fast fly-through doesn't queue renders for
     pages already scrolled past. Confirmed by the user: old lag gone.
  2. **Unrelated bug found + fixed while testing**: toggling single ↔ facing
     view jumped the main viewer to an unrelated page. Root cause:
     `relayout()`'s internal `updateVisible()` recomputed `curPage` off the
     still-stale `scrollTop` against the *new* layout, and the toggle handler
     then read that corrupted `curPage` to reposition scroll. Fixed by
     capturing `curPage` into `targetPage` before `relayout()` runs
     (`viewmodeBtn` handler in [`main.ts`](./opensdocx/src/main.ts)).
  3. **Dedicated worker for thumbnails** (option 3): `render.worker.ts`'s
     `onmessage` handler runs `renderJob()` synchronously, so a single Worker
     only ever does one raster at a time — sharing one worker between viewer
     and sidebar meant they always queued behind each other even on multi-core
     machines. `makeRenderPool()` now gives each its own Worker/job-map/id
     sequence (`mainRenderPool` / `thumbRenderPool`), running on separate OS
     threads. `THUMB_MAX_INFLIGHT` raised 2→3 (no longer trades off against
     the main viewer).
  4. **Algorithmic audit** (user pushed back on "just bring debug closer to
     release" as papering over a real inefficiency): checked
     `crates/sdocx/src/page.rs` `parse_page` and `opensdocx/src-tauri/src/lib.rs`
     `build_page_scene` — no waste found. `Reader::metadata()` is computed once
     at `open()` and cached (`container.rs:716`), `page_bytes()` is a plain zip
     extraction, `build_page_scene` is a linear O(n) DTO transform. The one
     double-work spot (`page.rs:348-349`, two layout hypotheses decoded per
     stroke) is intentional format-disambiguation logic validated
     zero-counterexample across the corpus — **do not touch it for perf**, out
     of scope, protected by the RE discipline above. Conclusion: the
     debug/release gap here is unoptimized-codegen overhead (no inlining, live
     bounds checks), not a hidden algorithmic bug. A `[profile.dev] opt-level =
     1` in `opensdocx/src-tauri/Cargo.toml` was proposed as a zero-extra-disk
     way to close much of that gap (same `target/debug/`, no `target/release`)
     but **was not applied** — the user wanted the JS/cache angle explored
     first; revisit this if a future round wants it.
  5. **Real bug found in the scene cache**: `getScene()`'s eviction
     (`main.ts`) was keyed only to the main viewer's `curPage`, which the
     sidebar never updates — scrolling the sidebar far from `curPage` caused
     its just-fetched scenes to be evicted almost immediately (cache cap was
     24), forcing a re-fetch loop while the user was still looking at them.
     Fixed: eviction now protects a radius around **both** `curPage` and a new
     `thumbCentrePage()` (sidebar viewport centre, same calc style as
     `updateVisible`'s `curPage`), and the cap was raised 24→200 (`SCENE_CACHE_MAX`
     — heuristic, not measured: scenes are structured data, not bitmaps, so
     much cheaper to keep; still bounded per the user's explicit request re:
     documents with thousands of pages).
  6. **New: idle-priority background scene warmer** (`scheduleWarm`/
     `warmStep`). After interactive rendering settles (`inFlight === 0 &&
     thumbInFlight === 0`), walks the whole document once (page 0 → last)
     filling the scene cache, so a cold jump anywhere — especially in the
     sidebar, which has no prefetch of its own — is more likely already warm.
     Single bounded sweep (doesn't re-chase pages the cap later evicts);
     `warmGen` invalidates a still-running sweep when a new document opens
     mid-warm (same stale-async-state pattern as `layoutGen`).
  **Net result, user's own words**: real improvement, old bugs gone, but
  "non sono particolarmente contento" — jumping to unexplored sidebar
  territory in a **debug** build still isn't as snappy as release. Parked
  here rather than pushed further this round; candidates for a future pass if
  revisited: the deferred `opt-level = 1` profile tweak (item 4), and/or
  auditing `resolveTemplateBitmap`'s scale-keyed PDF-template raster cache
  (noted mid-session: thumb-scale and full-view-scale each trigger their own
  from-scratch `pdf.js` rasterization for PDF-backed templates — only matters
  for Academic/Notebook/Planner-style documents, not investigated further).

- **TODO — resource/RAM (measured 2026-07-19, debug build, 66-page doc, sidebar
  open, before the round above):** ~556 MB PSS total (main `opensdocx` 254 MB —
  inflated by the 252 MB *debug* binary being mapped; `WebKitWebProcess` 275 MB;
  net process 28 MB). The app's own data was small and bounded by
  virtualization at the time of measurement; note the scene-cache cap is now
  200 instead of 24 (item 5 above) — still small (structured data, not
  bitmaps) but not re-measured, worth a sanity check if this is revisited.
  Realistic **release** footprint ≈250-350 MB, dominated by WebKitGTK's own
  baseline (unavoidable for a webview app; still lighter than Electron since
  Tauri uses the system WebKit). Quick win when it matters: build `--release`
  + strip (debug bin 252 MB → ~15-20 MB) — though the user has flagged that
  building release locally costs disk space they don't want to spend
  routinely, so treat this as occasional validation, not a dev-loop step.

- **TODO — export follow-ups (2026-07-20), no urgency, revisit when there's
  appetite.** Export (SVG/PNG/PDF, per-page + whole-document PDF) shipped
  this round; three loose ends flagged by the user, not yet scoped:
  1. **Evaluate whether other export formats are needed** beyond SVG/PNG/PDF
     (e.g. something print-shop-friendly, or a lighter web format) — no
     concrete request yet, just worth periodically asking "is this enough."
  2. **Whole-document export for SVG/PNG, not just PDF.** Today only PDF
     exports the entire document in one action (`export_document_pdf` /
     CLI `export pdf`); SVG/PNG export only the current page
     (`export_page`). Evaluate adding a whole-document SVG/PNG path too
     (likely N separate files, mirroring `opensdocx-cli`'s existing
     no-`--page` per-page-file behavior) — and surface it in the app UI,
     not just the CLI (today's export menu only exposes per-page SVG/PNG +
     whole-document PDF).
  3. **No progress feedback during export.** Clicking an export menu item
     gives no visual indication anything is happening — no spinner/progress
     bar, no disabled-state feedback — even though a multi-page PDF export
     is NOT instant (feels slow in practice, likely worth a real look, not
     just a spinner slapped on top of the current timing). Needs both a UI
     affordance (progress indicator, keep the export button disabled/busy
     mid-export) and an actual perf investigation into why it's slow before
     assuming a progress bar alone fixes the experience.

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
- **Favorited/starred note** (APK-RE pending validation, 2026-07-14): `end_tag.bin`
  `property_flags` bit 1 has a disputed meaning — either `is_landscape` (negative-tested)
  or `is_favorite` (app-code static RE hypothesis). Zero positive evidence on the
  30-sample corpus. Mark a note as favorite/starred in Samsung Notes and export it to
  settle which bit actually toggles. See `docs/format/sample-wishlist.md` #13 and
  `docs/format/unknowns.md`.
- **`mediaInfo.dat` reference-count / attached-flag edge semantics**,
  **`end_tag.bin` variant coverage** (non-empty SDK strings/custom
  data/skipped/encryption blocks, true landscape-lock setting), **image/painting flex fields**, and
  **`ext_block.seq`/`counter`**: bounded but still need isolated samples for
  semantic edge cases.
- **Smooth curve fitting for handwriting strokes** (render-side, not a format
  gap): we currently render strokes as polylines. Reference project
  `squ1dd13/sdocx2pdf` (Rust, MIT, active as of 2026-07-18) fits smooth Bézier
  curves instead — clean events, interpolate+upsample position/pressure,
  Gaussian-filter the time-domain derivatives, compute curvature to find key
  vertices/inflection points, then join them with pressure-width "bean"-shaped
  Bézier fills (see their `sdocx2pdf/src/stroke.rs`). Worth a look if we ever
  prioritize handwriting-render fidelity over the current polyline approach.

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
