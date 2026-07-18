# Sample wishlist

Targeted ground-truth `.sdocx` samples that would close specific entries in
[`unknowns.md`](./unknowns.md). Rule stays: **one variable at a time,
user-created, never invented** (see `CLAUDE.md`). Mirrors the agent-memory
copy of this list so it's visible in the repo; update both when status
changes, or just this file if the memory copy is stale.

Legend: **DONE** (closed, sample exists and was decoded) · **OPEN** (still
wanted) · **PARTIAL** (sample exists but doesn't fully close the question).

## Closed since 2026-07-09

- ~~Note with a template applied~~ → per-*page* custom-image `template_uri`
  is DONE (`PagLiscia&templatescustoms`, `Pagvuota&templatescustoms`,
  retroactively `Appunti vari`). The *note-level* `template_uri` flex field
  is a different field and is still open — see below.
- **Shared/attached-file note** → DONE. `Shared Notebook1_260710_000433.sdocx`
  decodes `attached_files` and `server_check_point` (both fully parse, not
  just structurally present). `author_info`/`app_name`/`app_version` were
  *not* populated in that sample — still open, see below.
- **All builtin "Basic" page templates in one file** → DONE,
  `AlltypeofPageBasic_260709_200911.sdocx` + `AllTypeofPageBasic/` GT photos.
  Ids 1-9, 11 named and pitch-calibrated. Id 10 does not exist in the current
  app (confirmed by user 2026-07-11) — drop, not a gap.
- **Empty page vs one-stroke page in the same note** (`content_bbox` presence
  gate) → DONE, `PaginaVuota&Paginapuntino_260711_122434.sdocx`.
- **Light vs dark theme** (`property_flags` bit 0x8) → DONE (2026-07-11),
  `Default-darkmode-Liscio_260711_153256.sdocx` has `property_flags = 8`
  against a baseline of `0` everywhere else in the corpus. Confirms
  `is_background_colour_inverted`.
- **Landscape note** → DONE as a *negative result* (2026-07-11),
  `Importedlandscape_260711_153103.sdocx`. The page itself is genuinely
  landscape (1600×928, via a builtin "Landscape Grid" PDF template, not an
  imported image), but `end_tag.bin`'s `is_landscape` bit stays `0`. So
  page-aspect-ratio and the document-level `is_landscape` flag are
  decoupled — the flag likely tracks a separate orientation-lock setting we
  haven't triggered. No further sample needed unless a way to set that
  device-level flag is found.
- **Bookmarks** → DONE as a negative result, `Segnalibri_260709_225650.sdocx`
  (see `unknowns.md` — not exported at all).
- **Rotated text-box geometry** (storage/midpoints at all 8 angles) → DONE,
  `TextboxAllAngles_260709_231912.sdocx`. The *wrap-layout* question is only
  PARTIAL — see below.

## Open — Priority A (note.note flex fields, 0/14 corpus so far)

1. **Note-level `template_uri`** (bit 6) — distinct from the per-page
   custom-image path above; this is the flex field for a template applied
   from Samsung's template *store/picker* at the note level.
2. **Shared/authored note with a real author** → `author_info` (bit 2),
   `app_name`/`app_version` (bits 0/1). `Shared Notebook1` didn't populate
   these; need a note actually co-edited or shared with visible authorship.
3. **AI text summarisation used** (if the device supports it) →
   `text_summarisation` (bit 20).

## CLOSED (2026-07-11) — Priority B: table style-tail semantics

Closed by the `Tabella4x3Regolare` (v1) + `Tabella4x3Regolarev2` samples — a
4×3 grid with one styling change per page, each backed by rendered-PDF ground
truth. Everything decoded and gated (see
[tables.md](./container/note-note/tables.md) and
`spec/ksy/sdocx_table_object.ksy`):

- **Per-cell character styling** — `font_size`, `bold`, `strikethrough`,
  `foreground_color` spans, confirming the `text_core` span-type names against
  ground truth for the first time (italic/underline already confirmed by the
  typed-text corpus).
- **Per-cell background fill** — `cell_fill_argb` (`sfondo blu` = `ffdaecfb`).
- **Custom column widths** — the `col_width` f32 array; plus a 10×4 grid with
  empty cells and an invisible all-off 5×2 as free edge cases.
- **Border blocks (v2)** — first block = outer frame, second = inner grid
  lines; per entry `ARGB + width + corner radii`; entries 0/2 vertical, 1/3
  horizontal; disabled = zeroed; radii 26 → 0 on "bordi netti a 90°".
- Corrected: table-wrap `rows_minus_1` → 0-based **table_index**; the cell
  preamble carries a table-wide **styled flag**.
- **Merged cells: N/A** — the UI exposes no merge action (user, 2026-07-11).

Residual micro-gaps (not worth dedicated samples unless trivial to make):
left-vs-right / top-vs-bottom within a border pair, custom border
colour/width (the UI may not expose them), and a recoloured "evidenzia"
header to confirm the beige is `theme_fill_argb`.

## Partial — Priority B: controlled typed-text layout

**Core flow campaign delivered 2026-07-13.**
`OnlytextTypewritten-Sistematic-carattere15_260713_212435` supplies 50 uniform
15-unit rows across three PDF pages, and
`OnlyTypeWrittenTextDifferentFont_260713_212408` supplies repeated 11/14/19/64
blocks with a font-matched empty row after each block. Together they ground the
line-box transform, empty-row height and page-break rule; page assignments now
match the vector exports 50/50 and 32/32. See
[`heuristics.md`](./heuristics.md#measured-gt-audit-and-controlled-pdfs-2026-07-13).

The remaining Priority-B requests are independent `line_spacing` choices and
controlled body/heading space-before/after presets. The font-size follow-up is
closed for the observed sizes; intermediate sizes are no longer necessary to
derive the linear advance, though they would remain useful counterexamples.

4. **Samsung line-height and pagination model — exact remaining campaign.**
   Font-size advance, font-matched empty rows and whole-line pagination are now
   grounded. To close Priority B completely, provide the following controls.
   Separate `.sdocx` files are strongly preferred: they prevent a style change
   from leaving hidden state on the following block.

   **A. One note for each remaining line-spacing choice (required).** The
   existing systematic size-15 note is already the control for its current
   spacing, so do not recreate that setting.

   - Portrait document/body text only: no handwriting, lists, headings, blank
     lines, tables, images, text boxes or manual page objects.
   - Keep the same default font family and stored size **15** throughout.
   - Select exactly one of Samsung Notes' other line-spacing choices and enter
     **50 short explicit lines**, enough to cross at least one automatic break:
     `LS <setting> LINE 001 - Hgjpqy 0123456789`, incrementing only the number.
   - Make one file per spacing choice and put the UI setting in its filename,
     for example `TypedText-LineSpacing-Narrow` / `...-Wide`. If the UI shows
     only icons, include a screenshot of the selected icon and number them from
     narrowest to widest.
   - Keep portrait size and page template fixed. Medium square grid is useful,
     but use the same template as the existing systematic sample if possible.

   **B. One paragraph-style transition note (required).** This isolates the
   independently decoded `space_before`, `space_after` and style presets.

   - Default font family, stored size **15**, and the same line-spacing choice
     used by the existing systematic sample. No blank lines or wrapping.
   - Start with 8 consecutive plain/default-body paragraphs:
     `BODY CONTROL 01 - Hgjpqy`, through `08`.
   - For every paragraph preset exposed by the UI (Body/default, Body 1,
     Body 2, Heading 3, Heading 2, Heading 1), add this alternating sequence,
     with the preset applied only to each `STYLE` line:

     ```text
     BODY <preset> 01 - Hgjpqy
     STYLE <preset> 01 - Hgjpqy
     BODY <preset> 02 - Hgjpqy
     STYLE <preset> 02 - Hgjpqy
     BODY <preset> 03 - Hgjpqy
     STYLE <preset> 03 - Hgjpqy
     BODY <preset> 04 - Hgjpqy
     STYLE <preset> 04 - Hgjpqy
     ```

     Alternating both directions is intentional: `BODY → STYLE` isolates the
     style's leading gap, while `STYLE → BODY` isolates its trailing gap.
   - Do not manually change font size after choosing a preset: we need the
     preset's native size and spacing exactly as Samsung applies them.
   - If Samsung exposes manual paragraph space-before/after controls, make a
     separate note for each non-default value using the same 8-line alternating
     pattern. If those controls do not exist, nothing extra is needed.

   **C. In-app ground truth for glyph anchoring (required, no new note).** The
   vector PDFs determine line-box spacing exactly, but not whether Samsung's
   editor uses the same font anchor as its PDF exporter.

   - Capture every visible page of the two already delivered notes
     `OnlyTypeWrittenTextDifferentFont_260713_212408` and
     `OnlytextTypewritten-Sistematic-carattere15_260713_212435` directly in
     Samsung Notes, especially the pages containing size 64.
   - Hide keyboard, caret, selection and editing handles. Use one unchanged zoom
     and include the full page edges. Lossless device screenshots are preferred;
     otherwise use perpendicular photos with all four corners visible.

   **For every new note:** export `.sdocx` and PDF from the exact same settled
   state as the captures, without editing between them. Keep captures in page
   order and record Samsung Notes version, device model, display/font scaling,
   selected font family, font size, line-spacing choice and page template.

   With A+B+C, the remaining line-spacing multipliers, paragraph-gap conversion,
   page-break behaviour and editor glyph anchors are independently measurable;
   no further typed-text-layout sample should be necessary unless one of these
   controls reveals a new format flag or a PDF/editor divergence.

## Open — Priority C: text/objects

5. **Text-box wrap heuristic**: `TextboxAllAngles` proved geometry but its
   4-character text is too short to calibrate wrapping. Need a **long
   identical string in identical-size boxes at 0/90/180/270°** — same text,
   same box dimensions, only rotation varies.
6. **PARTIAL — `Mathsolver&Hyperlink`:** the hyperlink is an inline Web object
   type 13, not span type 9; Math Solver emits ordinary styled text plus
   per-stroke `RecogUIFeature_MathStrokeUuidStringArray`, not formula span 23.
   A different-font run (type 4), and direct span types 9/23 if the current UI
   can produce them, remain open.
7. Text box with **vertical alignment** centre/bottom → `Common` gravity
   values 1/2 (corpus is all 0 today).
8. **DONE — Web object:** `Mathsolver&Hyperlink` contains inline object type 13
   anchored in the body text, its URL/preview payload, and an `@web_*.jpg`
   thumbnail. Corrected: this is a text-inline object, not a page object.
9. **Audio variants**: multi-recording note, a renamed recording, and one
   where the audio widget is visibly placed on the page → settles whether
   page object type 10 (Audio) ever appears in exports.
10. **Image inserted then deleted**, and one **image reused twice** in the
   same note → `mediaInfo.dat` `ref_count` / `is_attached` edge semantics.

## Open — Priority D: existing campaigns

11. **`HDR_EXT.counter` isolation**: create one shape, duplicate it, modify
    one copy, copy it to another page → separates object lineage vs. group
    lineage vs. copy/edit generation.
12. **Absolute-f64 stroke variant**: reproduce the coordinate-pair (not
    delta) stroke encoding seen on a couple of benchmark pages — suspicion
    is shape-converted or imported strokes.
13. **Favorited note** → `end_tag.bin` `property_flags` bit 1 is `0` on the
    whole 30-sample corpus (no sample has ever set it). App-code static RE
    (private `apk-re/`, not this repo) found a Java `SetFavorite`/`IsFavorite`
    pair reading/writing this exact bit, which would mean the current
    `is_landscape` label is wrong (see `unknowns.md`) — but that's still an
    unconfirmed hypothesis: mark a note as favorite/starred in Samsung Notes
    and export it to see whether `property_flags` becomes `2`.

## External validation (not a "make a sample" item)

`samples/samsung2.sdocx.zip` is a real Android-exported (Galaxy Tab) file
attached to [squ1dd13/sdocx2pdf#1](https://github.com/squ1dd13/sdocx2pdf/issues/1),
where it reportedly crashes that (unrelated, Rust) tool ("failed to read
character data" / "Not a directory"). Checked against our own pipeline
2026-07-11: **parses cleanly** — `pysdocx dump`/`text`/`objects`/`inventory`
all succeed, 0 unknown tail bytes, 0 sha mismatches, title/strokes/media all
resolve normally. Zip-level inspection (flag bits, compression method,
extra fields) shows nothing structurally different from our other samples
either. Whatever sdocx2pdf chokes on isn't reproduced here and isn't a real
format variant we're missing — most likely a bug in their own zip handling.
Worth keeping in the corpus (rename to `.sdocx`) as an external cross-check
sample, but it doesn't unlock a new decode.
