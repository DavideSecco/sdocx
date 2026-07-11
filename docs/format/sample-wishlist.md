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

## Open — Priority B: table style-tail semantics

The type-22 table object's **framing and geometry are byte-exact** (round
14); only the *style tail* (border-block ARGB + 3 floats ×2 edges,
per-column f32 arrays, trailing scalar + final ARGB) is still unmeasured,
because every table in the corpus so far uses default styling.

**What to make — 4 separate files, one change each vs. a plain baseline
grid** (keep it isolated per the project's one-variable rule; don't combine
into one file):

- **Baseline** (if not already just the existing plain-grid tables): a
  simple 3×3 table, default borders, default column widths/row heights, no
  shading, no merges. Put a short unique label in each cell (e.g. `A1`,
  `B2`, …) so cells stay identifiable by their decoded text run regardless
  of geometry.
- **Sample 1 — merged cells**: same 3×3 grid, merge two adjacent cells
  horizontally in one place and two adjacent cells vertically in another.
  Isolates how a merge is represented in the row/cell length-chain (does a
  merged cell still emit two cell records, or does `n_cols` drop for that
  row?).
- **Sample 2 — custom borders**: same 3×3 grid, change color *and*
  thickness on a couple of edges only (not all four), ideally one outer
  edge and one inner edge so the two border-block entries can be told
  apart. Leave everything else default.
- **Sample 3 — custom column widths / row heights**: same 3×3 grid, drag
  two columns to different explicit widths and one row to a different
  height. Isolates the per-column f32 array vs. the row `height` field
  already known from the framing.
- **Sample 4 — cell background shading**: same 3×3 grid, fill 2-3
  individual cells with different background colors (not the whole table).
  Isolates the trailing per-cell/table ARGB semantics.

Keep each file **table-only, no audio, no other page objects** — the
existing type-22 corpus is small (2 notes, 18 cells) and audio pages have
historically added unrelated parsing noise. Any short label text is fine;
it doesn't need to be meaningful.

## Open — Priority C: text/objects

4. **Text-box wrap heuristic**: `TextboxAllAngles` proved geometry but its
   4-character text is too short to calibrate wrapping. Need a **long
   identical string in identical-size boxes at 0/90/180/270°** — same text,
   same box dimensions, only rotation varies.
5. Typed text containing a **hyperlink**, a **formula** (if available), and
   a run in a **different font** → span types 9/23/4.
6. Text box with **vertical alignment** centre/bottom → `Common` gravity
   values 1/2 (corpus is all 0 today).
7. **Web object**: a shared web page / link-preview card in a note → page
   object type 13 (`sdocx2pdf` calls it `Web`; we have no schema at all).
8. **Audio variants**: multi-recording note, a renamed recording, and one
   where the audio widget is visibly placed on the page → settles whether
   page object type 10 (Audio) ever appears in exports.
9. **Image inserted then deleted**, and one **image reused twice** in the
   same note → `mediaInfo.dat` `ref_count` / `is_attached` edge semantics.

## Open — Priority D: existing campaigns

10. **`HDR_EXT.counter` isolation**: create one shape, duplicate it, modify
    one copy, copy it to another page → separates object lineage vs. group
    lineage vs. copy/edit generation.
11. **Absolute-f64 stroke variant**: reproduce the coordinate-pair (not
    delta) stroke encoding seen on a couple of benchmark pages — suspicion
    is shape-converted or imported strokes.

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
