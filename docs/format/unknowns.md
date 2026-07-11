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
- **Header preamble structure** (between the fixed leading fields and `base`):
  still not modeled. It is what forces the paper record `[BGRA][u32
  display_width]` — and the template fields that follow it — to be located **by
  signature** instead of a fixed offset: the record sits at 0x80/0xa4/0x13e/0x15e
  depending on the (unknown) preamble, the `kind` u32 before it is 2/3 on most
  notes but not present at all on some families (PDF-template content pages match
  only via the display-width fallback), and imported-PDF notes put ~4000 where
  `kind` normally sits. **This is the single unlock for modeling the paper color
  + template/PDF-link fields in `sdocx_page.ksy`** — until the preamble is
  decoded, they stay procedural (`_locate_paper_record` in pysdocx/Rust) per the
  "no scans in a .ksy" rule. A grounded attack is viable: 150+ corpus pages, and
  the preamble length correlates with `base`.
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
