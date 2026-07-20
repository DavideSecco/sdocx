# `<uuid>.page`

One per page. Carries the page header (dimensions, UUID, content bounding box)
followed by a **layer/object tree** holding all the per-page graphics: ink
strokes, shapes, images, drawings, and in-page text boxes.

- **Formal spec (header + layer/object tree):**
  [`spec/ksy/sdocx_page.ksy`](../../../../spec/ksy/sdocx_page.ksy)
  (validated on all 161 corpus pages — see [validation](#validation)).
- **Reference parser:** `parse_page` / `parse_page_tree` / `_parse_object_header`
  in [`pysdocx/page.py`](../../../../pysdocx/page.py).
- **Conventions:** [`../../00-conventions.md`](../../00-conventions.md).

## Sub-pages

| Topic | Nature | Page |
|---|---|---|
| Common object header + `field_flags` size model | **Decoded** | [`object-header.md`](./object-header.md) |
| Non-stroke payload-geometry wrapper | **Decoded** | [`payload-geometry.md`](./payload-geometry.md) |
| Stroke payloads (delta-compressed coords) | Marker / procedural | [`strokes.md`](./strokes.md) |
| Shapes / images / drawings / text boxes | mixed | [`object-types.md`](./object-types.md) |

## Page header — Decoded

Little-endian. Named fields hold with zero counterexamples across all 161 corpus
pages. Offsets are absolute in the `.page` member.

```
offset  size  field           status    note
0x00    4     base            Decoded   offset where the layer tree starts
0x16    4     page_width      Decoded
0x1a    4     page_height     Decoded
0x26    2     uuid_char_len   Decoded
0x28    ...   uuid            Decoded   UTF-16LE (= member filename, pageIdInfo)
0x80    32    content_bbox    Decoded   optional 4 x f64 [x_min,y_min,x_max,y_max]
end-58  32    page_hash       Decoded   copied into pageIdInfo.dat (see below)
end-26  26    footer_signature Decoded  "Page for SAMSUNG S-Pen SDK"
```

`content_bbox` is present iff the serialized layer tree declares at least one
object. On pages with an empty tree it is physically omitted and the next
preamble field begins at `0x80`. This gate is modeled in `sdocx_page.ksy` by
the lazy `tree.has_objects` instance: the tree lives later at `base`, but Kaitai
can inspect it without confusing the bytes at `0x80` for four floats. Proven by
`PaginaVuota&Paginapuntino_260711_122434.sdocx` and checked corpus-wide.

### The full preamble as a sequential field-flags structure — Decoded

The table above is a *reading* of fixed offsets that happen to hold on the
current corpus. `pysdocx/page_header.py` decodes the same bytes as what they
actually are: a sequential header (`page_end_offset` == `base`, `flex_offset`,
variable-length property/field-flags bitfields, orientation, `width`,
`height`, `offset_x`, `offset_y`, `uuid`, `modified_time`, `format_version`,
`min_format_version`) followed by a **field-flags-gated optional region**
between `flex_offset` and `base` — the same region the table above just calls
"where the layer tree starts". Cross-referenced from `squ1dd13/sdocx2pdf`
(MIT, see [`xref-sdocx2pdf.md`](../../xref-sdocx2pdf.md#page-header--promosso))
and validated with **zero counterexamples on 214/214 corpus pages**
(`spec/tools/validate_page_header.py`): the region always consumes exactly
`base - flex_offset` bytes.

Field-flags bits, in bit order (`FIELD_NAMES` in `pysdocx/page_header.py`):

| bit | field | note |
|---|---|---|
| 0 | `drawn_rect` | == `content_bbox` above; presence matches `object_count > 0` on 226/226 |
| 1 | `tags` | vector of short UTF-16 strings; unseen on the corpus |
| 2 | `template_uri` | custom-image template path; supersedes `page_custom_template_uri`'s heuristic (which occasionally over-reads one leading UTF-16 code unit) |
| 3-7 | `background_image_id/mode/colour/width/rotation` | `background_colour` (BGRA) matches `page_background_color`'s heuristic byte-for-byte, 226/226 |
| 8 | `pdf_data_items` | embedded-PDF page placements: `[file_id, page_index, rect]*`; matches `page_pdf_template`'s single-entry heuristic on 25/25, and additionally finds a **20-entry** case (`samples/cs61bl_su22`, one tile per vertical page-height slice) the heuristic misses entirely — not yet wired into rendering |
| 9 | `template_type` | 17-variant enum (`TEMPLATE_TYPE_NAMES`); matches the "Basic" template id from `page_template`'s heuristic id-for-id everywhere both fire, and names ids 10/12-15 that table below didn't have (Todo/Custom/Weekly/Monthly/Manuscript — Marker naming from sdocx2pdf, not yet grounded against our own hand-labeled sample) |
| 10 | `canvas_cache_map` | keyed `CanvasCacheEntry` records (49 bytes each: 4-byte key + 45-byte entry) |
| 11-12 | `imported_data_height`, `theme` | Unknown semantics; `theme` sdocx2pdf calls "skipped by the libs" |
| 15-16 | `recognised_data_modified_time`, `stroke_recognition_data` | opaque blobs, unseen on the corpus |
| 18 | `custom_objects` | sticky notes (`CustomObjectType::StickyNote`, id 1) — see below |

**`custom_objects` / sticky notes**, decoded structurally (previously only
found by a whole-page `co_attach_file` marker scan, `scan_sticky_notes`):
`uuid`, `attached_files` map (`co_attach_file` -> media bind id, matches the
marker scan), `custom_data` map (`skn_collapse_rect` matches the marker scan;
**`skn_bg_color`** is new — a signed-decimal Android ARGB colour string,
`"-6482"` == `0xFFFFE64E`, a warm cream, on all 3 corpus instances), and an
outer `rect`. Two things not yet resolved: the outer `rect` and
`custom_data["skn_collapse_rect"]` are two *different* bounding boxes on
every observed instance (which one is the real on-page icon placement needs
a targeted sample — a GT-photo check was inconclusive, see
[`unknowns.md`](../../unknowns.md)); and every instance (3/3) carries an
unmodeled 8-byte trailer after `rect` (two `u32`s, both `5303`) that
sdocx2pdf's own parser doesn't expect (`ensure_eof()` right after `rect`) —
kept as `trailing_raw`, semantics Unknown.

No `.ksy` yet for this region — `spec/tools/validate_page_header.py` is the
gate. `pysdocx.page.parse_page()` exposes the decode as `page["header"]`
(best-effort: `None` if a page falls outside the validated corpus shape,
which has not happened yet). The legacy heuristic scanners
(`_locate_paper_record`, `page_template`, `page_background_color`,
`page_custom_template_uri`, `page_pdf_template`) are unchanged for now —
they're mirrored in `crates/sdocx/src/page.rs`, so swapping their internals
to the structural read is a separate follow-up round.

### Page footer — Decoded

Every `.page` ends with a 32-byte page content hash immediately followed by the
ASCII signature `Page for SAMSUNG S-Pen SDK` (the per-page analog of
`end_tag.bin`'s `Document for S-Pen SDK`). That 32-byte hash is exactly what
[`pageIdInfo.dat`](../pageIdInfo.md#page_recordpage_hash--32-bytes--74--decoded-source-found)
stores as the page's `page_hash` — the manifest copies it. The test gate
cross-checks the two per page (161/161). Reference: `parse_page_footer` in
[`pysdocx/page.py`](../../../../pysdocx/page.py). How the page computes the hash
is still Unknown; the manifest↔page linkage is decoded.

### Paper (background) color — Decoded

Each page stores its **paper color** in the header preamble as a small record:

```
[u32 kind] [B G R 0xFF] [u32 display_width]
   kind ∈ {2, 3}         BGRA, alpha == 0xFF   device paper width (px)
```

The record's *absolute* offset varies with a variable-length header preamble
(seen at `0x84` / `0xa4` / `0x13e` / `0x15e`), so it is **located by that
signature** within `[0x7c, base)` rather than a fixed offset — the earlier
fixed-offset guess (`0x84`/`0x80`/`0xa4` keyed on `base`) misread `base==0x8c`
pages as having *no* paper. The signature yields exactly one match on all
**122 pages** of the 14-sample corpus **+** the 4 one-variable background samples
in [`samples/test-background/`](../../../../samples/test-background/) (zero
counterexamples). Reference: `page_background_color` in
[`crates/sdocx/src/page.rs`](../../../../crates/sdocx/src/page.rs).

The `test-background` samples pin the field: `Default` `(252,252,252)`, `Bianca`
`(230,230,230)`, and — decisively — **`Rosina` `(245,221,221)`** (a pink paper,
the only sample whose value is unmistakably a tint), all differing *only* in the
paper. Every corpus note carries a **single light paper across all its pages**
(mostly `(252,252,252)`), so `note.note` does **not** store this — the paper is a
per-`.page` field. The record's **field sequence** is now decoded — a fixed
`[obj_id][seq][4000][4000]` block at 0x70, then optional `content_bbox` /
`template_uri` / `[u32 kind]`, then this paper record, then the template fields
(see [unknowns.md `.page`](../../unknowns.md#page)). The `content_bbox` gate is
now structural in Kaitai; the URI/kind/paper/template gates remain procedural
because they have no independent serialized discriminant. The decode also
surfaced a **third page-template
mechanism**, `template_uri` (a custom-image template path in the app's private
storage; newer exports may also embed a matching `media/` image) — see
unknowns.md.

The **template** is *not* a single fixed field: its offset depends on `base`, so
it is decoded procedurally (`page_template`) and documented with the object types
rather than modeled in the `.ksy`. There are **three families** — procedural
"Basic" backgrounds, custom picker images, and PDF-backed templates (Academic
multi-page + imported PDFs).

### Custom-image templates — Decoded and rendered

`PagLiscia&templatescustoms_260711_122117.sdocx` isolates a plain page followed
by a picker-image template. The page preamble adds a NUL-terminated UTF-16LE
app-private path before `kind` and the paper record. In this export the archive
also contains `media/0@files_231229_092644_140.jpg`, whose basename matches the
URI; there is no placed-image object on the page. `page_template` therefore
returns `kind: image` plus the URI/basename. Pysdocx and OpenSdocx resolve that
basename against `media/` and draw the image full-page beneath page content.
The matching asset is embedded in both known cases, including the pre-existing
`Appunti vari` sample (see [unknowns.md](../../unknowns.md#page)); no sample
with the asset genuinely absent has been observed. If a future sample lacks the
match, rendering falls back to the paper fill.

### Plain-page thumbnail link — Decoded (procedural)

Normal plain content pages carry a page-thumbnail media reference relative to
the paper record `M`:

```
M+8   u32  1
M+C   u16  49
M+E   u16  Unknown (0/1 observed)
M+10  u16  Unknown
M+12  u16  thumbnail_media_index -> media/<index>@page_….spi
```

`page_thumbnail_media_index` resolves to an actual `.spi` media record on 12/12
applicable corpus pages. Template families use different post-paper tails and
are excluded. The link remains procedural with the rest of the paper/template
record until those gates can be expressed without signature lookahead in KSY.

### Basic background template ids — Decoded (naming), Heuristic (pitch)

`samples/AlltypeofPageBasic_260709_200911.sdocx` cycles through Samsung Notes'
"Basic" background picker, one id per page, each page hand-labelled by the user
with the on-device name — a decisive, zero-ambiguity source for the id→name
mapping (unlike the pitches, which are measured off matching ground-truth
photos in `samples/AllTypeofPageBasic/`, RE 2026-07-09). `id` → `(category,
name)`, `TEMPLATE_NAMES` in [`pysdocx/page.py`](../../../../pysdocx/page.py):

| id | category | name | pitch (page units) |
|---|---|---|---|
| *(no template field)* | blank | Blank page | — |
| 1 | line | Lined (narrow) | 72.5 (row only) |
| 2 | line | Lined | 102.5 (row only) |
| 3 | line | Line (wide) | 168.0 (row only) |
| 4 | grid | Grid (narrow) | 72.5 (square) |
| 5 | grid | Grid | 102.5 (square) |
| 6 | grid | Grid (wide) | 168.0 (square) |
| 7 | dot | Dot (narrow) | row 72.5 / col 79.7 |
| 8 | dot | Dot | row 102.5 / col 110.0 |
| 9 | dot | Dot (wide) | row 168.0 / col 174.8 |
| 10 | — | **missing from the sample** | — |
| 11 | oxford | Oxford | rule 65.5, red margin at x≈235 |

Line and grid templates share one narrow/default/wide pitch triple
(72.5/102.5/168.0) — measured independently for each category and landing on
the same numbers within photo-measurement noise. Dot is the outlier: its
lattice is **not square** — column pitch runs consistently ~7-10% wider than
row pitch at every id (blob-centroid clustering on the GT photos, 15-27 dots
per axis) — the row pitch still matches the shared triple, but the column
pitch is dot-specific (`DOT_SPACING_BY_ID`). Oxford has its own rule pitch
(65.5, unrelated to the shared triple) plus a single vertical red margin
rule (`OXFORD_MARGIN_X`/`OXFORD_MARGIN_COLOR`) — the color is a JPEG-averaged
approximation, not a decoded value. All of the above are render heuristics
(see [heuristics.md](../../heuristics.md#grid-template-pitches)), not decoded
fields — `category`/`name` are the only decoded part of this table. id 10
never appeared in the sample and needs a dedicated capture; the grid origin
(`GRID_ORIGIN`, top margin) is reused as-is for line/dot/oxford, unverified
per-category.

### PDF-backed templates — Academic & imported PDF — Decoded

The "Academic" template families (Notebook, Planner, …) and any **imported PDF**
are *not* procedural: the artwork is a **real PDF embedded under `media/`**, and
each `.page` references one of its pages. This is a fundamentally different
mechanism from the Basic ids above — nothing is drawn from constants, the
background *is* the referenced PDF page.

The reference lives in the 8 bytes right after the paper record `M` (the
`[BGRA][u32 display_width]` quad that `page_background_color` locates by
signature — see `_locate_paper_record`, which grew a width-match fallback because
these notes put a non-2/3 value where `kind` normally sits):

```
M+8  u16 flag              == 1 on every observed PDF page (a count? — assumed)
M+A  u16 pdf_media_index   -> media/<index>@<name>.pdf in the archive
M+C  u16 reserved          == 0 on PDF pages; == 1 on Basic pages (M+8 = template id there)
M+E  u16 pdf_page_index    -> 0-based page within that PDF
```

`flag == 1 && reserved == 0` separates PDF pages from Basic ones with **zero
counterexamples across the 150-page corpus**. `page_pdf_template` decodes it;
`page_template` returns `{kind: "pdf", pdf_media_index, pdf_page_index}` (no
`name` — the template's identity is the PDF's archive filename, not a stored id).

Ground truth: `samples/Notebook&Planner1_260709_213306.sdocx` embeds
`media/0@07_StudyTemplates_A4_v2.pdf` (7 pp, "Notebook") and
`media/2@01_PlannerTemplates_A4_v2.pdf` (6 pp, "Planner"). Each PDF's
`mediaInfo` **`ref_count == 7`** = 6 empty template pages + 1 "content" page (the
one the user wrote a label on, `base==0xfd`, which references page index **0**).
Indices are 0-based, so Study uses 0–6 and Planner 0–5; the exported
`…_gt.pdf` is exactly those 13 template pages with the strokes composited on top.
The same field also (correctly, now) decodes the single imported-PDF page in
`quiz.sdocx` (`media/0@pdf_…​.pdf`, page 0) — which the old base-keyed decoder
mislabelled as the Basic "Lined (narrow)" id.

Rendering uses this directly: `pysdocx.render.rasterize_pdf_page` rasterises the
referenced embedded PDF page (via `pypdfium2` — pdfium, the same engine the
Rust/Tauri app targets) and composites it as the full-page background under the
strokes. The A4 PDF page has the same aspect as the 1600×2264 sdocx page, so it
fills the page with no distortion; verified page-for-page against the exported
`…_gt.pdf`. The rasteriser is optional — without it the background is simply
omitted (graceful degradation), the link is still decoded.

Two things are **not** decoded here: the `flag` semantics (always 1 so far —
possibly a count for multi-template pages), and the mapping from PDF *filename*
(`07_StudyTemplates_A4_v2`) to a human template name / Samsung's built-in
catalog (the latter would need the Samsung Notes APK, a separate concern — the
embedded PDFs are self-contained, so nothing external is needed to render).

## Layer / object tree — Structural

Starting at `base`: `u16 layer_count`, `u16 current_layer_index`, then that many
layers. Each layer has a prefix, a next-offset, three flag bytes + a
`content_flags` byte, a `layer_flags` u32, then a set of **optional** fields
gated by `content_flags` bits:

| `content_flags` bit | Adds |
|---|---|
| `0x01` | 1 byte |
| `0x02` | 4 bytes |
| `0x04` | UTF-16 string (a UUID) |
| `0x08` | UTF-16 string → `layer_uuid` |
| `0x10` | `s64` modified time |
| `0x20` | 4 bytes |

Then `u32 object_count`, the objects themselves, and a 32-byte layer hash. Each
object entry stores its `raw_type`, child count, and **size**, so object
boundaries are deterministic — the parser walks the tree by stored sizes rather
than resyncing byte-by-byte (which is what lets mixed pages keep their
handwriting between non-stroke records).

This structure is now modeled in Kaitai as `SdocxPage.tree`. Each object entry
uses a substream of `blob_size` bytes, whose first bytes are parsed as the
common `sdocx_object_header`; semantic payload decoding remains procedural.

Current corpus layer invariants (161/161 pages):

- exactly one layer per page; `current_layer_index == 0`;
- `layer_prefix == 0x62`;
- flag triple `(flag1, flag2, flag3) == (1, 2, 1)`;
- `content_flags == 0x18`, so each layer carries `layer_uuid` and
  `modified_time` and none of the other optional fields;
- `layer_flags == 0`;
- every layer has a 32-byte hash after its object tree.

These are structural facts, not full semantics for the flag bits. Future
multi-layer samples are needed before naming `layer_flags` or the other
`content_flags` options.

### Object types in the corpus

```
OBJECT TYPES  stroke 96622 · shape 424 · image 58 · text_box 16 · drawing 1
RAW TYPES     1:96622 · 7:351 · 8:73 · 3:58 · 2:16 · 14:1
```

Every observed object type is classified — there is no backlog of "seen but
unclassified" object types on the current corpus.

## Validation

```bash
KSC_GEN=<scratch>/gen .venv/bin/python spec/tools/validate_page.py
# -> 161 matched, 0 mismatched, out of 161 pages
KSC_GEN=<scratch>/gen .venv/bin/python spec/tools/validate_page_tree.py
# -> 161 page trees matched, 0 mismatched, 97121 objects, out of 161 pages
```

The header validator compares `base`, `page_width`, `page_height`, `uuid`, and
`content_bbox` (bytewise, to survive NaN) against `parse_page`. The tree
validator compares layer counts, flags, optional-field boundaries, object entry
offsets (`off`, `blob_off`, `end`), raw type, child count, blob size, recursive
child order, and the 32-byte layer hash against `parse_page_tree`.
