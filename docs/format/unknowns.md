# Open questions

Every field/behaviour that is present in the bytes but **not yet decoded**, in
one place. Each stays Unknown deliberately: the 14-sample corpus bounds it
structurally but cannot isolate its meaning without samples that vary one
variable at a time. The discipline is "an honest Unknown over a speculative
name" ([conventions](./00-conventions.md)).

## `pageIdInfo.dat`
Both manifest hashes are decoded as **copies**. `head_hash = note.note[-32:] =
sha256(note.note[:-32])` (13/13), so the document-level hash construction is
decoded. `page_hash = the .page footer hash` (48/48), but the **page footer hash
construction** remains open: no plain `sha256`/`sha3_256`/`blake2b` of the raw
member reproduces it, and a full contiguous-range brute force on the smallest
page finds nothing. Likely a canonical/serialized input or a keyed construction.

## `note.note`

The member is now **sequentially decoded end-to-end** (`pysdocx/note_doc.py`,
`spec/ksy/sdocx_note.ksy`): header, title/body Text blobs, field-flag-gated
flex fields (string registry, pen records, voice recordings, …), trailing
hash. The former tail-record unknowns (preload param hints, pen_style_tail,
tail_hash_block prefixes, tail_post_hash_u32, voice post fields) are resolved
as flex fields — see `container/note-note/tail-records.md`. What remains:

- **`pre_flex_gap`**: 0 or 8 bytes before the flex fields; when 8, a u32 pair
  `(width, round(width*sqrt(2)))` — default-page-size candidate, does not
  always match real `.page` sizes.
- **Unexercised flex fields** (modeled from sdocx2pdf, still 0/corpus):
  `app_name`, `app_version`, `author_info`, `latitude_longitude`,
  `template_uri` (the note-level flex field — distinct from the per-`.page`
  custom-image `template_uri` below, which IS decoded), `compatible_last_pen_info`,
  `fixed_font`, `text_summarisation`, `stroke_group_size`, `app_custom_data`;
  field-flag bits 4, 5, 8 are not modeled at all (would break the sequence if
  ever set). `attached_files` and `server_check_point` are no longer in this
  list — both decode cleanly on `Shared Notebook1_260710_000433.sdocx`.
- **`text_core::Common` residue:** `section_data` pair semantics; paragraph
  type 6 (`parsing_state`, ≈ one record per character); the two non-boolean
  strikethrough span payloads on the benchmark; the trailing `(3,2)`/`(0,0)`
  u32 pair of inline objects; `interval_type` values beyond their enum names.
- **Shape/Text wrapper residue:** the full ObjectBase → ShapeBase → Shape →
  Text chain and its frame boundaries are decoded and Kaitai-gated. Common is
  reached by Shape's `flex_offset`, not scanning. Remaining micro-unknowns are
  the semantics of constant ShapeBase bytes, Shape flex bit 11's optional f32
  (`11.0` on the sole mixed-font instance; exposed as `shape_field_11_f32`),
  and the 32-byte hash-like trailer
  on page text boxes (0/16 match `sha256(wrapper_without_trailer)`).
- **Tables:** framing, geometry, cell character/fill styling, column widths,
  outer/inner borders and theme fill are decoded and Kaitai-gated on 20 tables
  / 260 cells. Residue is limited to constant head/flag bytes, left-vs-right or
  top-vs-bottom identity within equivalent border pairs, and a few default
  width-constraint semantics; merged cells are not exposed by the current UI.
- **Rotated text-box** inner text padding / logical frame (currently
  [heuristic](./heuristics.md#rotated-text-box-wrapping)).

## `.page`
- **Header preamble — field sequence Decoded; `content_bbox` gate Decoded;
  remaining template gates Unknown (RE 2026-07-11).**
  The bytes between the fixed leading fields and the paper record are now mapped
  (`M` = paper-BGRA offset, located by `_locate_paper_record`):
  ```
  0x00 base · … · 0x16 width · 0x1a height · 0x26 uuid_len(=36) · 0x28 uuid[72]
  0x70 [u32 obj_id][u32 seq≈415k][u32 4000][u32 4000]          (fixed)
  then, in order, each OPTIONAL:
    [content_bbox : 4×f64]        presence correlates with the serialized object tree
    [template_uri : UTF-16, NUL-terminated]   a custom-image template path (see below)
    [u32 kind = 2|3]              present on normal pages, ABSENT on the PDF family
    [BGRA paper][u32 display_width]            = M
    [template fields]             normal: [u32 id][u32 1] · PDF: [u16 1][u16 media][u16 0][u16 page]
  ```
  Observed `M` ∈ {0x80,0x84,0xa0,0xa4,0x13e,0x15e}, entirely explained by which
  optionals are present. There is no dedicated bbox flag byte: its gate is the
  later layer tree's declared object count. Kaitai can nevertheless model this
  through a lazy instance, so `content_bbox if tree.has_objects` is now formal
  and validator-backed. The gates still blocking the rest of the preamble are:
  `kind` — absent only for `base ∈
  {0xa6,0xfd}` (the whole PDF family), but `base` is itself downstream of the
  preamble length; `template_uri` — only 4 pages (2 notes), too few to isolate.
  So per the "no scans in a `.ksy`" rule URI/kind/paper/template records stay
  procedural (`_locate_paper_record`).

  The controlled `PaginaVuota&Paginapuntino_260711_122434.sdocx` closes the
  presence observation: page 1 is intentionally empty (`object_count=0`, paper
  `M=0x84`), page 2 has one stroke (`object_count=1`, bbox at `0x80`, paper
  `M=0xa4`), and Samsung added a trailing empty page matching page 1. Thus the
  bbox is physically omitted when this page tree is empty and inserted when the
  dot exists. The dependency on downstream tree state is now the decoded gate;
  it does not require a speculative signature lookahead.
- **`template_uri` (NEW, 2026-07-10) — a third page-template mechanism.** Beyond
  Basic (procedural id→pitch) and PDF-backed (embedded `media/…​.pdf`), a page
  can reference a **custom image template** by absolute path in the app's private
  storage, e.g. `Z/data/user/0/com.samsung.android.app.notes/app_templates/added/
  files_231229_092644_140.jpg` — stored as a UTF-16 string in the preamble. The
  matching asset is embedded in both known instances: `Appunti vari` (3 pages,
  not previously recognized as a template asset before `template_uri` decoding)
  and `PagLiscia&templatescustoms_260711_122117.sdocx` both contain
  `media/0@files_231229_092644_140.jpg`, whose basename exactly matches the URI;
  in the latter the page has strokes only and no placed-image object, so that
  member is unambiguously the custom template asset. `page_template` now
  reports `kind: image`, and both pysdocx and OpenSdocx resolve the embedded
  asset by basename and composite it as a full-page background. No sample with
  the asset absent has been observed (2/2 embedded); the earlier "not embedded,
  path only" note (2026-07-10) was written before `template_uri` decoding
  existed and was never re-checked against `Appunti vari`, which already had
  the matching media member. Rendering still degrades to the paper color if a
  future sample lacks the match, but that is a defensive fallback, not an
  observed case. Distinct from the `note.note` `template_uri` flex field.
- **PDF-template record `flag` (M+8)**: `== 1` on all 15 observed PDF-backed
  pages (2 Academic PDFs + 1 imported). A count for multi-template pages? Needs
  a sample with >1 template PDF on one page family.
- **Basic template id 10**: never appeared in the AlltypeofPageBasic sample
  (ids 1-9, 11 all named from the user's handwritten labels); name and pitch
  unknown. Needs a dedicated capture.
- **Object header `flags`** (u16): constant `0x1bf` on non-stroke objects; on
  strokes only bit `0x1` varies (an invariant, not a clean semantic).
- **`ext_block.seq` / `ext_block.counter`**: `seq` near-constant per note (not
  per-object, not monotonic); `counter` repeats / groups related-or-copied
  objects. No clean semantic.
- **`extra_key` trailing `u32 = 1`**: constant; flag-vs-count undecidable.
- **Raw-absolute-`f64` stroke variant**: observed on a couple of benchmark pages
  (absolute coordinate pairs, not deltas); neither known layout reads it. The
  current corpus diagnostic scans only delta-inconsistent stroke objects by
  default and finds no count-prefixed/aligned absolute-f64 run, so this likely
  needs a targeted sample or a more specific signature.
- **Shape payloads:** complete formal schema for every variant; whether future
  shape families add payload-geometry point roles.
- **Image payload flex fields:** `sdocx2pdf` names crop/original/border fields;
  our diagnostic confirms the known media ref as a `u32` on 15/15 image objects,
  but does not yet isolate crop/original/border field offsets.
- **Drawing/Painting payload:** `sdocx2pdf` names attached file, thumbnail, ratio,
  crop rect, and original rect; our diagnostic confirms the known media ref as a
  `u32` on the only corpus drawing object, but a larger corpus is needed before
  promoting the rest.
- **Text-box trailer:** the wrapper and former 16-byte structured residue are
  decoded (`text_auto_fit_type` + the Text frame). Only the final 32-byte
  hash-like value remains Unknown; it is not plain SHA-256 of the preceding
  wrapper bytes on any of the 16 text boxes.
- **Attachment placement:** structural page-object model when the object tree is
  empty (sticky/audio pages); recursive decode of nested sticky-note `.sdocx`.
- **Layer/content flags:** full semantics of all layer `content_flags` and
  `layer_flags` bits (boundaries known; not every bit meaning).

## `media/mediaInfo.dat`
- The 11-byte tail is decoded as
  `[u16 ref_count][u64 modified_time][u8 is_attached]`, cross-checked against
  `sdocx2pdf`. Remaining caveat: current corpus variety is weak for the semantic
  edge cases (`is_attached` is always true; `ref_count` needs samples that vary
  attachment references/deletion states).
- Shared/COEDIT notes may insert a `CONTENT_FILE_DATA_LIST` block between the
  ordinary media records and `EOFX`. Its marker, `u32` count, and length-framed
  record boundaries are decoded; the record bodies' collaboration metadata is
  still Unknown. First observed in `Shared Notebook1_260710_000433.sdocx`.

## `end_tag.bin`
- **`is_landscape` (negative result, 2026-07-11):** `property_flags` bit 1
  stays `0` even in `Importedlandscape_260711_153103.sdocx`, whose page is
  genuinely landscape (1600×928, via a builtin "Landscape Grid" PDF
  template). So document-level `is_landscape` is decoupled from per-page
  aspect ratio — it likely tracks a separate orientation-lock setting never
  triggered here, not the shape of the page content. Treat as closed unless
  a way to set that device-level flag turns up.
- **Variant coverage:** SDK strings, skipped blocks, encryption data, and
  non-empty custom data are structurally modeled but not exercised.
- **Older-sample display timestamp units**: `display_created_time` /
  `display_modified_time` are ms-close (not exact) on the 3 older imports.

## Cross-file leads worth a targeted sample campaign
- **Page bookmarks / “Segnalibri” export (negative result, 2026-07-11):** in
  `Segnalibri_260709_225650.sdocx`, pages 1 and 3 are bookmarked and page 2 is
  not. No differentiating bookmark field appears in `pageIdInfo.dat`,
  `note.note`, page header/layer flags, or the stroke-only object trees. The
  apparent per-page values `0,2,1` are instead decoded thumbnail media indices,
  each linking to its ordinary `.spi`. No explicit bookmark state is therefore
  recoverable from this export; Samsung Notes likely keeps it outside `.sdocx`.
- A **"only text box at 0/90/180/270°"** family would isolate whether the rotated
  text-box wrap bug is missing geometry metadata or pure layout logic.
- More **audio** samples (multi-audio, renamed, page-visible audio widgets)
  would settle whether the `note.note` → `.m4a` linkage is the only exported
  model here or whether some exports contain `sdocx2pdf`'s page object type 10.
- **External validation, not a gap (2026-07-11):** `samples/samsung2.sdocx.zip`
  is a real Android-exported (Galaxy Tab) file attached to
  `squ1dd13/sdocx2pdf#1`, where it reportedly crashes that unrelated Rust
  tool. It parses cleanly end-to-end here (0 unknown tail bytes, 0 sha
  mismatches) and its zip framing is structurally identical to our other
  samples — whatever sdocx2pdf chokes on isn't a real format variant we're
  missing.

See [`sample-wishlist.md`](./sample-wishlist.md) for the full list of
samples that would close the remaining open questions above.
