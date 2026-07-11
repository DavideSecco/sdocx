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

- **`property_flags` (alias `flags`) bit `0x8`**: sdocx2pdf names it
  `is_background_colour_inverted`; corpus values 0x0/0x8 only, semantic
  untested here (Marker).
- **`pre_flex_gap`**: 0 or 8 bytes before the flex fields; when 8, a u32 pair
  `(width, round(width*sqrt(2)))` — default-page-size candidate, does not
  always match real `.page` sizes.
- **Unexercised flex fields** (corpus 0/14, modeled from sdocx2pdf):
  `app_name`, `app_version`, `author_info`, `latitude_longitude`,
  `template_uri`, `compatible_last_pen_info`, `attached_files`,
  `server_check_point`, `fixed_font`, `text_summarisation`,
  `stroke_group_size`, `app_custom_data`; field-flag bits 4, 5, 8 are not
  modeled at all (would break the sequence if ever set).
- **`text_core::Common` residue:** `section_data` pair semantics; paragraph
  type 6 (`parsing_state`, ≈ one record per character); the two non-boolean
  strikethrough span payloads on the benchmark; the trailing `(3,2)`/`(0,0)`
  u32 pair of inline objects; `interval_type` values beyond their enum names.
- **Title/body Text wrapper**: the Shape/Text object bytes around the Common
  frame (the frame is found by scan, not fixed offset).
- **Tables:** the type-22 object's *framing and geometry are decoded
  end-to-end* (byte-exact, 2/2 notes, 18/18 cells; the old "cell marker" was
  the cell outline's last path point + the closepath opcode). Still Unknown:
  the style-tail *semantics* (border-block entries and their 3 floats, the two
  per-column f32 arrays, the trailing scalar and final ARGB), a handful of
  constant head/flag bytes, and everything never varied on the corpus (merged
  cells, custom borders/widths/shading) — see
  `container/note-note/tables.md`. Needs a table-only sample family.
- **Rotated text-box** inner text padding / logical frame (currently
  [heuristic](./heuristics.md#rotated-text-box-wrapping)).

## `.page`
- **Header preamble — field sequence Decoded, presence gates Unknown (RE 2026-07-10).**
  The bytes between the fixed leading fields and the paper record are now mapped
  (`M` = paper-BGRA offset, located by `_locate_paper_record`):
  ```
  0x00 base · … · 0x16 width · 0x1a height · 0x26 uuid_len(=36) · 0x28 uuid[72]
  0x70 [u32 obj_id][u32 seq≈415k][u32 4000][u32 4000]          (fixed)
  then, in order, each OPTIONAL:
    [content_bbox : 4×f64]        present on content pages, absent on empty/template pages
    [template_uri : UTF-16, NUL-terminated]   a custom-image template path (see below)
    [u32 kind = 2|3]              present on normal pages, ABSENT on the PDF family
    [BGRA paper][u32 display_width]            = M
    [template fields]             normal: [u32 id][u32 1] · PDF: [u16 1][u16 media][u16 0][u16 page]
  ```
  Observed `M` ∈ {0x80,0x84,0xa0,0xa4,0x13e,0x15e}, entirely explained by which
  optionals are present. **What blocks modeling this in `sdocx_page.ksy`: the
  presence GATE of each optional is not a clean structural field in the corpus.**
  A byte-level discriminant search over 154 pages found: `content_bbox` — *no*
  single byte separates present/absent (it tracks "page has content", i.e. the
  object tree, which lives after `base`); `kind` — absent only for `base ∈
  {0xa6,0xfd}` (the whole PDF family), but `base` is itself downstream of the
  preamble length; `template_uri` — only 3 pages (one note), too few to isolate.
  So per the "no scans in a `.ksy`" rule the paper/template records stay
  procedural (`_locate_paper_record`) until a **targeted sample campaign** pins
  the gates: an empty vs one-stroke page in the same note (bbox gate), and a
  custom-image-template note vs a plain one (uri gate).
- **`template_uri` (NEW, 2026-07-10) — a third page-template mechanism.** Beyond
  Basic (procedural id→pitch) and PDF-backed (embedded `media/…​.pdf`), a page
  can reference a **custom image template** by absolute path in the app's private
  storage, e.g. `Z/data/user/0/com.samsung.android.app.notes/app_templates/added/
  files_231229_092644_140.jpg` — stored as a UTF-16 string in the preamble. The
  image is NOT embedded in the `.sdocx`, so such a background is unrenderable from
  the file alone (only the path is recoverable). Seen on 3 pages of one note
  (`Appunti vari`). Distinct from the `note.note` `template_uri` flex field.
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
- **Text-box wrapper residue:** the box's `text_core::Common` frame is now
  decoded on 8/8 blobs (offset 386 non-rotated / 406 rotated, margins
  `[8,4,8,4]`, spans equal to the scans); what remains Unknown is the
  Text/Shape wrapper bytes before the frame (incl. the rotated boxes'
  20-byte extra) and the fixed 48-byte post-frame tail (16 structured bytes +
  a 32-byte hash-like value).
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

## `end_tag.bin`
- **Variant coverage:** property flags are zero on the current corpus, so
  `is_landscape` needs a landscape sample; SDK strings, skipped blocks,
  encryption data, and non-empty custom data are structurally modeled but not
  exercised.
- **Older-sample display timestamp units**: `display_created_time` /
  `display_modified_time` are ms-close (not exact) on the 3 older imports.

## Cross-file leads worth a targeted sample campaign
- A **"only text box at 0/90/180/270°"** family would isolate whether the rotated
  text-box wrap bug is missing geometry metadata or pure layout logic.
- More **audio** samples (multi-audio, renamed, page-visible audio widgets)
  would settle whether the `note.note` → `.m4a` linkage is the only exported
  model here or whether some exports contain `sdocx2pdf`'s page object type 10.
