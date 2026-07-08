# Cross-reference: `squ1dd13/sdocx2pdf`

Source compared: `https://github.com/squ1dd13/sdocx2pdf`, cloned outside this
repo in `/tmp/sdocx2pdf-xref` with `git clone --depth 1`.

All `sdocx2pdf` field names below are **hypotheses for this repo** until they
are validated on our 13-sample corpus with the usual zero-counterexample gate.
Entries explicitly marked **PROMOSSO** or **HASH CONFERMATO** have passed that
gate here; the remaining semantic edge cases are still called out separately.

## 5 quick wins

1. **`mediaInfo.dat` "magic" is `format_version`**: `sdocx2pdf` treats
   the leading `u32` before the record count as the note format version for
   `EOFX` manifests (`sdocx/src/media_info.rs:68-83`), matching our observed
   `0x1518 == 5400` / `0x1452 == 5202` values formerly called `magic`
   (`spec/ksy/sdocx_media_info.ksy:25-30`).
2. **`mediaInfo.dat` tail semantics**: their record tail is
   `_ref_count: u16`, `_modified_time: timestamp`, `is_attached: bool`
   (`sdocx/src/media_info.rs:105-124`), exactly our structural
   `[u16 ref_count][u64 modified_time][u8 is_attached]`
   (`pysdocx/container.py:166-190`).
3. **`end_tag.bin` raw islands are SDK fields**: their parser names
   `is_landscape`, `cover_image`, app version, page model, document type, owner
   id, display timestamps, fixed font/direction/theme, orientation, and custom
   data (`sdocx/src/end_tag.rs:245-316`); our parser/spec/docs now expose the
   same sequential footer and validate it on 13/13.
4. **Text/text-box inner schema**: `text_core::Common` has an explicit length
   framed text object with spans, paragraphs, margins, gravity, sections, and
   inline objects (`sdocx/src/page/object/text_core.rs:271-359`), whereas we
   currently pattern-scan runs and paragraph records (`pysdocx/note.py:129-227`,
   `pysdocx/page.py:1466-1495`).
5. **Image/drawing payload fields**: `Image` and `Painting` decode crop rect,
   original rect, attached file IDs, thumbnail IDs, border data, and ratio
   (`sdocx/src/page/object/image.rs:49-94`,
   `sdocx/src/page/object/painting.rs:43-68`), beyond our current marker-based
   placement/media-index extraction (`pysdocx/page.py:1301-1340`,
   `pysdocx/page.py:1417-1463`).

## License

`sdocx2pdf` is MIT licensed. The root manifest declares `license = "MIT"`
(`/tmp/sdocx2pdf-xref/Cargo.toml:5-6`). The license file is the standard MIT
text with `Copyright (c) 2026 squ1dd13` (`/tmp/sdocx2pdf-xref/LICENSE:1-3`) and
allows use, copy, modification, merge, publication, distribution, sublicensing,
and sale (`/tmp/sdocx2pdf-xref/LICENSE:5-10`) if the copyright and permission
notice are included in copies/substantial portions (`/tmp/sdocx2pdf-xref/LICENSE:12-13`).

No source-file SPDX/copyright headers were found outside `LICENSE` and config
comments (`rg -n "SPDX|Copyright|License" /tmp/sdocx2pdf-xref --glob '!*.svg'
--glob '!Cargo.lock'`).

**Verdict:** MIT is permissive and OSS-compatible. We may port/derive logic into
another OSS project if we preserve attribution/license notice for copied or
substantially derived portions. MIT has no copyleft requirement; derivative
project files may remain under our existing license if license compatibility is
otherwise satisfied. For clean-room RE discipline, prefer using their parser as
independent evidence and re-expressing validated facts in our own code/docs; if
we copy logic closely, add MIT attribution.

## Summary by object/surface

| Surface | Verdict | Why |
|---|---|---|
| `text` / `text_core` | **PROMOSSO (note-level)** | Their `Common` frame (text, spans, paragraphs, margins, gravity, sections, inline objects) is now decoded and validated corpus-wide for note title/body + table cells (`pysdocx/note_doc.py`, `docs/format/container/note-note/typed-text.md`). Page text boxes remain a separate variant (frame visible on only 2/8 blobs). |
| `shape` | **NUOVO** | They model formal shape/type/fill/template/control-point fields and a much broader shape enum; we decode rendered outline well but not full payload schema. |
| `shape_base` / `line` | **NUOVO** | They decode line colour/style effects, caps, joins, arrows, connection points, slave UUIDs; we infer arrow/line geometry from markers. |
| `painting` / drawing | **NUOVO** | They decode object type 14 as attached file, thumbnail, ratio, crop/original rect; we scan media index/hash/bbox. |
| `audio` / voice object | **NUOVO / CONFLITTO?** | They decode page object type 10; our current corpus sees audio through `note.note` tail/media manifest and pages with empty object trees. Variant/corpus gap to test. |
| `web` | **NUOVO** | They decode object type 13 with html file, thumbnail, body/title/uri, image type, version, view type; we have no web-object schema. |
| `image` | **NUOVO** | They decode crop/original/border fields; our media index, placement, rotation are already decoded. |
| `object base/header` | **CONFERMA + NUOVO** | Both parse length-prefixed object headers, flags, bbox, angle/flex fields. They name many property/flex bits we leave Unknown. |
| `stroke` pressure/tilt | **CONFERMA** | Their compressed/uncompressed event layouts match our pressure/tilt/timestamp model; they also name more stroke flex fields. |
| `mediaInfo.dat` | **CONFERMA + PROMOSSO** | Our former `magic/tag/time_candidate/marker` correspond to their `format_version/ref_count/modified_time/is_attached`; parser/spec/docs now use the new names with compatibility aliases. |
| `end_tag.bin` | **CONFERMA + PROMOSSO** | Their richer SDK struct explains our former raw islands; parser/spec/docs now expose the sequential footer with compatibility aliases. |
| `note.note` | **PROMOSSO** | Their sequential `note_doc` schema (bitfields, header, title/body blobs, flag-gated flex fields: string registry, pen info, voice records, attached files, …) is now decoded end-to-end and validates on 14/14, landing exactly on the trailing hash (`pysdocx/note_doc.py`, `spec/ksy/sdocx_note.ksy`). Two local improvements over their parser: the 8-byte pre-flex gap decodes as a `(width, round(width*sqrt(2)))` pair, and inline objects carry `position` + 8 trailing bytes they don't model. |

## Detailed gaps

### Text / `text_core` — NUOVO

`sdocx2pdf`:
- Span type enum names foreground color, font size/name, bold, italic,
  underline, hypertext, background color, timestamp, strikethrough, formula
  (`sdocx/src/page/object/text_core.rs:27-65`).
- Each span is `[u16 size][u32 span_type][u32 start][u32 end][u32 interval_type][extra bytes]`
  (`sdocx/src/page/object/text_core.rs:108-127`).
- Paragraph type enum names indent, alignment, line spacing, bullet, parsing
  state (`sdocx/src/page/object/text_core.rs:131-145`), with records
  `[u16 size][u32 paragraph_type][u32 start][u32 end][extra bytes]`
  (`sdocx/src/page/object/text_core.rs:172-190`).
- Common text is an exclusive length-framed stream: long UTF-16 text, span vec,
  paragraph vec, four `f32` margins, `u8` gravity, section pairs, and optional
  inline objects for format >= 2035 (`sdocx/src/page/object/text_core.rs:269-346`).

Ours:
- `note.note` typed text is found as the longest UTF-16LE field with matching
  `u32 char_count` (`pysdocx/note.py:90-126`).
- Character styles are scanned as `18 00 <tag> 00 | pad | start | end | value | enabled`
  (`pysdocx/note.py:129-148`, `pysdocx/note.py:258-306`).
- Paragraph metadata is scanned as `14 00 <tag> 00` and `1c 00 05 00...`
  (`pysdocx/note.py:151-227`).
- Text boxes reuse local style scans and expose text/bbox/angle/frame geometry
  (`pysdocx/page.py:1466-1495`).

Verdict: **PROMOSSO for note-level text (title/body/table cells).** The full
`Common` frame — text, span vector, paragraph vector, margins, gravity,
section data, inline objects — is decoded in `pysdocx/note_doc.py` and
validated with zero counterexamples against the TLV scans
(`spec/tools/analyze_note_doc.py`; docs in
`docs/format/container/note-note/typed-text.md`). The TLV families are exactly
serialized span/paragraph records; table cells are nested Common frames inside
a type-22 inline object. Two things their parser does not model were decoded
here: the inline-object tail (`u32 position` = U+FFFC anchor index + 8 unknown
bytes) and paragraph types 8/9/10 (space-before/after, style) missing from
their enum.

Next step (still open): page text boxes expose the frame on only 2/8 blobs at
the raw blob level — find the wrapper variant, then reuse `parse_common_frame`.

### Shape / shape payload — NUOVO

`sdocx2pdf`:
- Provides a broad `ShapeType` enum from 0 through 90, including many families
  absent from our corpus mapping (`sdocx/src/page/object/shape.rs:25-211`).
- Parses fill color/image/pattern/background effects, gradients, alpha/tiling,
  border type, original rect/angle, template path, control points, optional
  original drawn rect for pure shape objects (`sdocx/src/page/object/shape.rs:225-400`,
  `sdocx/src/page/object/shape.rs:586-646`).
- Shape flex fields include text common, text area type, pen name/default/style
  IDs, fill effect, border bytes, hint text/color/font/style, ellipsis/autofit,
  IME/input type, line-paper fields (`sdocx/src/page/object/shape.rs:646-689`).

Ours:
- Shape object status says membership/visual geometry are decoded but full
  formal payload schema remains Unknown (`docs/format/container/page/object-types.md:13-22`).
- We decode marker `01 04 04 01 00 00 00`, `type_code`, bbox, color, width, and
  flattened vector path / vertex fallback (`pysdocx/page.py:45-78`,
  `pysdocx/page.py:1729-1860`).
- Payload-geometry wrapper and per-shape point roles are decoded/inferred
  (`pysdocx/page.py:751-827`, `docs/format/container/page/payload-geometry.md:16-62`).

Verdict: **NUOVO hypothesis.** They give the formal shape payload envelope we
explicitly lack (`docs/format/unknowns.md:46-47`). No immediate conflict with
our rendered outline approach; they decode original/template/control data,
while we decode display path robustly.

Next step: add a non-rendering `shape-schema` diagnostic that parses object type
7 blobs using their sequence: `ShapeBase`, shape subheader type 7, `shape_type`,
`original_rect`, `original_angle`, optional path, `control_points`,
`original_drawn_rect`, then field-flag body. Compare `shape_type` to our
`type_code`, `original_rect`/bbox/path to our marker-derived bbox/path.

### Shape base / line — NUOVO

`sdocx2pdf`:
- `ShapeBase` parses points of connection, connection points with UUID lists,
  skip byte, line colour effect, line style effect, slave UUIDs
  (`sdocx/src/page/object/shape_base.rs:270-342`).
- Line colour/style effects include colour/gradient data, width, compound type,
  dash, cap, join, begin/end arrow shape/size
  (`sdocx/src/page/object/shape_base.rs:50-85`,
  `sdocx/src/page/object/shape_base.rs:196-233`).
- Object type 8 `Line` parses connector type, start direction, control points,
  start/end points, original drawn rect, original rect/angle, pen IDs, optional
  path (`sdocx/src/page/object/line.rs:60-107`).

Ours:
- We classify raw types `7/8` as shapes (`spec/ksy/sdocx_object_header.ksy:31-33`).
- Lines/arrows are markerless objects discovered by a shaft marker and fixed
  arrowhead flags (`pysdocx/page.py:1921-1986`).
- Unknowns still include complete shape payload schemas
  (`docs/format/unknowns.md:46-47`).

Verdict: **NUOVO hypothesis.** Their `Line`/`ShapeBase` likely replaces our
marker-scanned line/arrow semantics with a formal object-type-8 schema.

Next step: validate every current raw type 8 object by parsing line start/end
points and arrow shape/size from the field-flags schema, then compare against
`scan_arrows` geometry and `head_start/head_end`.

### Painting / drawing — NUOVO

`sdocx2pdf`:
- Object type 14 is `Painting`, with object base, subheader type 14, field flags:
  attached file ID, thumbnail ID, ratio default 1.0, crop rect `Rect<i32>`, and
  original rect `Rect<f64>` (`sdocx/src/page/object/painting.rs:40-68`).

Ours:
- We call raw type 14 `drawing`; media placement is marker/inferred from
  `05 00 00 00 [u32 media_index] [32-byte object hash]`, using object bbox or a
  nearby bbox fallback (`pysdocx/page.py:1343-1463`).
- Fuller object-level drawing payload semantics remain Unknown
  (`docs/format/container/page/object-types.md:32-38`,
  `docs/format/unknowns.md:48`).

Diagnostic result: `spec/tools/analyze_sdocx2pdf_leads.py` confirms the known
media reference as a `u32` on the one current painting/drawing object (1/1), but
does not isolate thumbnail, ratio, crop rect, or original rect.

Verdict: **NUOVO hypothesis.** Their `attached_file_id` likely corresponds to
our `media_index`; their crop/original rect may explain nearby bbox/crop data,
but only the media-ref presence is currently cross-checked.

Next step: align the type-14 flex stream around the confirmed `u32` media ref
and compare any plausible thumbnail ID, ratio, `crop_rect`, and `original_rect`
with mediaInfo and object bbox. The corpus has only one object, so new samples
are needed before promotion beyond media-ref presence.

### Audio / voice — NUOVO / possible CONFLITTO

`sdocx2pdf`:
- Object type 10 is `Audio`: object base, subheader type 10, property flag
  `is_recorded`, flex fields `attached_file_id`, `title`, `play_time`
  (`sdocx/src/page/object/audio.rs:43-74`).
- `note_doc` also parses voice recordings as file ID, name, duration string,
  creation time, action/time events, precise duration (`sdocx/src/note_doc.rs:187-260`).

Ours:
- Current audio linkage is conservative in `note.note` tail: label/duration,
  candidate media index, actual duration/time candidates, raw post fields
  (`pysdocx/note.py:425-454`, `pysdocx/note.py:659-772`).
- Page object docs say current audio sample pages have empty object trees; audio
  placement is unknown and surfaced via media manifest instead
  (`docs/format/container/page/object-types.md:53-62`).
- Unknowns request more audio samples to settle `note.note -> .m4a`
  (`docs/format/unknowns.md:68-72`).

Verdict: **NUOVO / CONFLITTO?** If Samsung exports audio as page object type 10
in some files, our current corpus simply lacks that variant. If our audio sample
should have type 10 but the layer count is zero, this is a format-variant
disagreement.

Next step: scan all page object trees for raw type 10; separately search raw
page bytes for type-10 inclusive subheaders. For any hit, compare
`attached_file_id` to `.m4a` `mediaInfo.dat` index. If no hit in 13 samples,
keep as external-variant hypothesis and request a targeted audio-object sample.

Current diagnostic result: 2/2 voice clips link to `.m4a` mediaInfo records, but
the corpus has 0 page object type-10 audio objects. This supports the
external-variant hypothesis for `sdocx2pdf`'s `Audio` page object.

### Web — NUOVO

`sdocx2pdf`:
- Object type 13 `Web` has attached html file ID, thumbnail file ID, body, title,
  uri, image type ID, version, and view type (`sdocx/src/page/object/web.rs:34-89`).

Ours:
- No web-object parser or documented web object type exists; attachments are
  currently image/audio/sticky/pdf/other via manifest and page marker scans
  (`pysdocx/container.py:331-339`, `pysdocx/page.py:1655-1689`).

Verdict: **NUOVO hypothesis.**

Next step: add inventory counters for raw type 13 and web-marker strings
(`http`, `https`, html filenames). If absent on current corpus, leave as
variant-support backlog.

### Image — NUOVO on internals, CONFERMA on placement/rotation

`sdocx2pdf`:
- Image is a subclass of `Shape`; after shape parsing it reads a type-3 subheader
  and flex fields: crop rect, border color/width/type, border image bind ID,
  nine-patch rect/width, border line width, original rect, original image bind ID
  (`sdocx/src/page/object/image.rs:34-94`).

Ours:
- Placement/media ref: `01 00 04 20` marker, media index before/ref-marker after,
  bbox after marker (`pysdocx/page.py:1238-1282`).
- Rotation: common header flag `0x1` gates `f32` degrees at offset 105
  (`pysdocx/page.py:1285-1298`), documented as decoded
  (`docs/format/container/page/object-types.md:23-30`).
- Payload geometry for images is decoded on 15/15 wrappers
  (`docs/format/container/page/payload-geometry.md:27-37`).

Verdict: **CONFERMA** for image object family and rotation/placement existence;
**NUOVO hypothesis** for crop/original/border fields.
`spec/tools/analyze_sdocx2pdf_leads.py` confirms the known media reference as a
`u32` on 15/15 image objects, but does not isolate crop/original/border field
offsets.

Next step: for the 15 current image objects, parse type-3 flex fields and compare
`original_image_bind_id`/`border_image_bind_id` with our media index; compare
`original_rect` and `crop_rect` to placement bbox and source image dimensions.

## Already-decoded surfaces

### Object base/header — CONFERMA + NUOVO

`sdocx2pdf` parses each object as an inclusive length-prefixed header:
`data_type`, `flex_offset`, variable-length property flags, variable-length
field flags (`sdocx/src/page/object/header.rs:43-75`). `ObjectBase` then reads
property flags (rotatable/selectable/movable/visible/etc.), format version, UUID,
modified time, rect, timestamp, resize mode, and flex fields such as angle,
attached file ID, min/max size, append time, owner page size, layout, thumbnail,
pivot, group ID (`sdocx/src/page/object/base.rs:188-260`).

Ours models a fixed common header whose field flags additively explain total
size, angle, extra key, hdr ext, and media family (`spec/ksy/sdocx_object_header.ksy:7-26`,
`docs/format/container/page/object-header.md:49-115`). `flags` semantics remain
Unknown (`docs/format/unknowns.md:34-40`).

Verdict: **CONFERMA** that the object header has property flags + flex field
flags and a bbox/angle model; **NUOVO hypothesis** for property flag names and
many flex fields.

Next step: extend inventory only, not `.ksy`, to decode `ObjectBase` property
bits and flex fields on all 11,788 objects; verify no contradictions with our
`total_size` additive model.

### Stroke — CONFERMA

`sdocx2pdf`:
- Compressed events store first point as f64/f32 origin, then `u16` deltas for
  point components, pressure, timestamp, and optionally tilt/orientation
  (`sdocx/src/page/object/stroke.rs:91-178`).
- Uncompressed events store all points as f64 pairs, pressures as f32,
  timestamps as u32, optional tilt/orientation f32 arrays
  (`sdocx/src/page/object/stroke.rs:180-223`).
- Stroke property flags name curve/replay/tilt/eraser/fixed-width/millisecond/
  top-layer/alpha/binary/generated/fixed-opacity bits
  (`sdocx/src/page/object/stroke.rs:406-421`).
- Stroke flex fields include advanced settings, color, pen size, pen name,
  fixed width, size level, particle density, rendering level, original width,
  tolerance, dash type/offset, stroke type, repeat distance
  (`sdocx/src/page/object/stroke.rs:431-464`).

Ours:
- We parse stroke objects after the common header and select current/shifted
  layout by bbox consistency (`pysdocx/page.py:844-895`).
- Stroke docs already treat pressure/intensity/width/color as decoded and keep
  render heuristics separate (`docs/format/container/page/strokes.md:50-68`).
- Absolute-f64 stroke variant remains open (`docs/format/unknowns.md:41-45`).

Verdict: **CONFERMA** for pressure/tilt/timestamp event layout. **NUOVO
hypothesis** for the named stroke property/flex bits, not required for current
rendering.

Next step: compare their `is_curve_enabled` branch against our `current/shifted`
selection and run the existing absolute-f64 diagnostic on any strokes that
`sdocx2pdf` would route through `parse_uncompressed_events`.

### Media info — CONFERMA + PROMOSSO

`sdocx2pdf`:
- Detects `EOFX`; for newer format it reads leading `_format_version: u32`
  (`sdocx/src/media_info.rs:68-83`).
- Each entry is length-prefixed, then `bind_id`, UTF-16 name, 64-byte hash,
  `_ref_count: u16`, `_modified_time: timestamp`, and newer-format
  `is_attached: bool` (`sdocx/src/media_info.rs:96-124`).

Ours:
- Formerly called the leading `u32` `magic`, with values `0x1518` and `0x1452`
  (`spec/ksy/sdocx_media_info.ksy:25-30`).
- Formerly called tail fields `tail_tag`, `time_candidate`, `tail_marker`
  (`pysdocx/container.py:166-190`), documented as Unknown semantics before
  promotion (`docs/format/container/mediaInfo.md:85-99`,
  `docs/format/unknowns.md:52-57`).

Verdict: **CONFERMA / PROMOSSO.** Their names line up byte-for-byte; this repo
now uses `format_version`, `ref_count`, `modified_time`, and `is_attached` as
the primary names, with old aliases retained for compatibility. Caveat:
`is_attached` is constant true on the current corpus and `ref_count` needs more
semantic edge-case samples.

Next step: collect samples that vary attachment references/deletion states to
stress `ref_count` and `is_attached`.

### End tag — CONFERMA + PROMOSSO

`sdocx2pdf`:
- Reads payload size, verifies trailing SDK ident, then parses `format_version`,
  `note_uuid`, `last_modified_time`, `is_landscape`, `cover_image`, width,
  height, app name/version, min format version, created time, last viewed page,
  page model, document type, owner id, optional skipped/encryption data, display
  created/modified/recognized times, fixed font, text direction, background
  theme, server checkpoint, orientation, min unknown version, app custom data
  (`sdocx/src/end_tag.rs:216-316`).

Ours:
- Now decodes the same sequential SDK footer: format version, note UUID,
  property flags / `is_landscape`, cover image, note size, app version, minimum
  format version, created time, last viewed page, page model, document type,
  owner/skipped/encryption fields, display timestamps, fixed font/text
  direction/background theme, server checkpoint, orientation, min unknown
  version, optional app custom data, and signature
  (`spec/ksy/sdocx_end_tag.ksy:21-125`,
  `docs/format/container/end-tag.md:27-126`).

Verdict: **CONFERMA / PROMOSSO.** The richer parser explains our former raw
regions byte-for-byte on 13/13 samples. Compatibility aliases remain for
`format_version_dup`, `created_time_a`, `created_time_b`, and
`extra_time_candidate`.

Remaining caveat: property flags are zero corpus-wide, and non-empty SDK
strings, skipped blocks, encryption data, and app custom data need targeted
samples.

### Note doc / `note.note` — NUOVO + hash confirmed

`sdocx2pdf`:
- Parses note metadata: background inversion flag, format version, ID, file
  revision, created/modified time, width/height, page padding, title/body text
  byte blobs, flex fields for app/version/author/location/template/last edited
  page/string registry/body font delta/pen info/voice data/attached files/server
  checkpoint/fixed font/direction/theme/text summarisation/stroke group/custom
  data (`sdocx/src/note_doc.rs:417-532`).
- Parses string registry (`sdocx/src/note_doc.rs:301-326`), pen info
  (`sdocx/src/note_doc.rs:101-184`), voice recordings
  (`sdocx/src/note_doc.rs:235-260`).
- Computes SHA-256 over exactly the consumed note-doc bytes and compares it with
  the following 32 bytes (`sdocx/src/note_doc.rs:547-570`).

Ours:
- Header/tail fixed parts are modeled conservatively in `sdocx_note.ksy`; rich
  text/tables/tail records are procedural scans (`future_todo.md`, current
  state).
- Unknowns include title object inner schema, tail records, voice clip post
  fields, and tail hash block prefix values (`docs/format/unknowns.md:19-32`).

Verdict: **PROMOSSO.** The whole sequential `note_doc` schema now validates on
14/14 with the positional hash gate: header + bitfields (our `flags` /
`meta_flags` are their property/field flags), title/body blobs, string
registry, pen info (simple + full), voice recordings with events, and the
enum-valued fixed fields (`pysdocx/note_doc.py`, `spec/ksy/sdocx_note.ksy`,
`spec/tools/validate_note.py`). The page footer hash remains a separate
unresolved construction.

Local additions beyond their parser: the sometimes-8-byte pre-flex gap (their
"fixme: eight-byte underread") decodes as a u32 pair
`(width, round(width*sqrt(2)))` on 12/12 occurrences, and the legacy
tail-record scans map one-for-one onto flex fields
(`docs/format/container/note-note/tail-records.md`).

## What is worth porting first

1. ~~Note-level `text_core::Common` payload parsing~~ — **done** (promoted
   with the full sequential `note_doc` schema, 2026-07-08).
2. Page text-box `Common` variant: find the wrapper offset so the promoted
   frame parser also covers the 6/8 text-box blobs that hide it.
3. `Image` / `Painting` flex-field alignment, because media refs are confirmed
   as `u32` on 60/60 objects but crop/original/thumbnail fields are not isolated.
4. Targeted audio-object samples, because current voice clips link to `.m4a`
   2/2 but page object type 10 is absent 0/14.
