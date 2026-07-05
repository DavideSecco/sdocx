# Handoff — field_flags RE round (2026-07-05)

Read this **after** `docs/OBJECT-HEADER-RE-NOTES.md` (the evidence) and `future_todo.md` (the older
checkpoint). Branch `feat/web-viewer`. **Nothing is committed** — the whole tree is one uncommitted body
of work. Corpus = the 13 `samples/*.sdocx`. No new samples were created.

## 0. Attribution (important — do not be misled)

This session (the "field_flags round") touched **only**:

- `pysdocx/page.py` — object-header `field_flags` decode + `ext_block` + profile promotion
- `pysdocx/inventory.py` — one line in `_note_profile` (`meta_tables_flag_0x2000`)
- `pysdocx/__main__.py` — CLI prints for the above (`header_features`, `ext_block seq=…`)
- `docs/OBJECT-HEADER-RE-NOTES.md` — filled in the field_flags evidence
- `docs/FORMAT-COVERAGE-INVENTORY.json` — regenerated

Everything else in the diff (`note.py`, `render.py`, `container.py`, `__init__.py`, most of
`inventory.py`, the other docs) is the **previous Codex block**, already uncommitted before this round.
Below, §3 answers your `note.py`/`render.py` questions but those are **previous-block** code, described
from reading the diff, not changed here.

---

## 1. What changed, file by file (THIS round only)

### `pysdocx/page.py`
- **`FIELD_FLAG_*` constants + comment block** (~line 124–148): decoded `field_flags` bits with the
  additive size model (see §2).
- **`_decode_header_ext(blob, field_flags)`** (~line 529): decodes the 16-byte extension gated by
  `0x40000`; returned on the header dict as `header["ext_block"]` = `{off, counter, seq, page_width,
  page_height}`. If `0x20` is also set, the decoder skips the preceding 32-byte `extra_key` block first
  (shifted decode verified 13/13; total ext dim match 1690/1690).
- **`_decode_extra_key_block(blob, field_flags)`**: decodes the 32-byte block gated by `0x20`; returned
  on the header dict as `header["extra_key_block"]` = `{off, head, head_ok, key_len, key, trailing}`.
  Verified after handoff: 40/40 blocks decode as `head=020100`, `key_len=23`,
  `key="extra_key_stroke_shape"`, `trailing=1`.
- **`_object_header_profile()`** (~line 635): rewritten. `known_features` now lists decoded bit names;
  `unknown_bits` is computed generically (any set bit not in `_FIELD_FLAG_KNOWN_MASK`) and is **empty
  across the whole corpus**. A novel bit in a future file would surface immediately.
- `EXTRA_KEY_STROKE_SHAPE = b"extra_key_stroke_shape"` constant added.

### `pysdocx/inventory.py`
- **`_note_profile()`**: promoted `meta_flags` bit `0x2000` → `meta_tables_flag_0x2000` (has-tables);
  marked `0x80|0x200|0x800|0x40000|0x80000` as `meta_base_bits` (constant); left `0x400/0x8000` and
  `flags 0x8` in `unknown_bits`.

### `pysdocx/__main__.py`
- `objects --detail` now prints `profile=…`, a `header_features known=[…] unknown_bits=[…]` line, an
  `ext_block off=… counter=… seq=… page=WxH` line, and an `extra_key_block …` line when present.

### `docs/OBJECT-HEADER-RE-NOTES.md`
- Filled the bit table, the `ext_block` decode, the `extra_key_stroke_shape` decode, and the
  object-header `flags`-field invariant.

### `docs/FORMAT-COVERAGE-INVENTORY.json`
- Regenerated via `pysdocx inventory samples --json`.

---

## 2. CERTAIN RE decodes (zero counterexamples across all 13 samples)

Offsets are within the object blob; base common header = `OBJECT_BASE_HEADER_LEN = 105`.

### 2a. `field_flags` additive size model
Every distinct `(total_size, field_flags)` signature reconstructs `total_size` additively from these
bits. Baseline `total_size` = **121** for stroke/text_box, **122** for image/shape/drawing.

| bit | name | size delta | evidence |
|---|---|---|---|
| `0x1` | rotation angle f32 @105 | +4 | already cracked for images |
| `0x20` | `extra_key_stroke_shape` block | +32 | see 2c — 40/40 |
| `0x40000` | 16-byte header extension | +16 | see 2b — width/height match 1690/1690 |
| `0x8000` | media/shape family bit | 0 | set on **all** image/shape/drawing, **no** stroke/text_box |
| `0x2000`,`0x4000` | base "present" bits | 0 | set on every object |

Examples: stroke `0x46021` = 121+16(`0x40000`)+32(`0x20`)+4(`0x1`) = **173** ✓; image `0x4e001` =
122+16+4 = **142** ✓. Verified: `pysdocx inventory samples` → `unknown_bits` empty everywhere.

### 2b. `0x40000` header extension (16 bytes) — `header["ext_block"]`
Offset `105 + (4 if 0x1 else 0) + (32 if 0x20 else 0)`. Layout
`[u32 counter][u32 seq][u32 page_width][u32 page_height]`.
- **page_width / page_height = the page header's dims on 1690/1690 objects.** This includes the 13 shifted
  cases where `0x20` is also set. Corpus has 4 distinct page sizes (`1600x2262`, `1080x27952`,
  `1812x15372`, `1848x7838`), so the match is real signal.
- `seq` / `counter` semantics are NOT settled. Current corpus facts: `seq` is near-constant within a note,
  not per-object, and not always monotonic; `counter` is not unique and often groups related/consecutive or
  copied objects.

### 2c. `0x20` `extra_key_stroke_shape` block (32 bytes) — CONFIRMED by background agent, 40/40
Offset `105 + (4 if 0x1 else 0)`. Fully accounted, invariant on all 40 objects that set the bit:
```
+0  [02 01 00]                       constant 3-byte head          40/40
+3  [17 00]                          u16 key length = 23           40/40
+5  ["extra_key_stroke_shape\0"]     22-char ASCII key + NUL       40/40
+28 [01 00 00 00]                    trailing u32 = 1 (never varies) 40/40
```
- Appears **only on stroke objects** (signatures `0x6020/0x6021/0x46020/0x46021`), on 5 pages of 4 files.
- **Negative result (honest):** despite the name, these strokes do **not** link to any inserted-shape
  object — `shapes=0`/`drawings=0` on every page carrying them, all 40 uuids unique. Best read as a
  per-stroke "shape/straight-line recognized" attribute, **not** a foreign key. Interpretation is a
  hypothesis; what's *decoded* is only the byte map + "no shape grouping".
- **Ordering confirmed:** on the 13 objects with both `0x20` and `0x40000`, the hdr_ext lands at
  `start+32` (after the extra_key block); its page_width/page_height match 13/13.

### 2d. Object-header `flags` field (the u16 before `field_flags`) — INVARIANT, not promoted
`0x1bf` on all non-stroke objects (constant capability field). On strokes, only bit `0x1` varies:
`flags0x1==0` ⇒ base-header basic pen (`tool_id∈{0,1}`, longer paths); every extended-header stroke sets
it. But within `tool_id=0` it still splits (2812 set / 7109 unset), so it is **not** a clean semantic.
Documented as an invariant only — deliberately **not** promoted.

### 2e. `meta_flags 0x2000 = has-tables` (note.note)
Set on exactly the 2 table-bearing notes, unset on all 11 others (incl. typed-but-tableless), and agrees
with independently-parsed table cells. `0x400/0x8000`/`flags 0x8` tested against wider observables
(pages/img/shape/sticky/template) → no clean feature → left `unknown`.

---

## 3. Previous-block behaviour you asked about (NOT changed this round)

Described from the diff so you have context; these are your earlier uncommitted work.

- **`note.py` `parse_note_metadata`**: top-level block decode (offset_to_data, flags, meta_flags,
  format_version, note_id, file_revision, created/modified time, width/height, paddings,
  min_format_version, title_size/title) + `voice_clips` + `tail_records`.
- **`note.py` `scan_note_tail_records(note_bytes, offset_to_data)`**: yields `tail_sentinel`,
  `voice_clip`, `pen_preload_path`, `tail_hash_block`.
- **`note.py` `annotate_note_tail_with_page_id_info`**: links `tail_hash_block` to the `pageIdInfo.dat`
  head (corpus: 10 exact + 3 shifted).
- **paragraph space_before/space_after**: decoded in the typed-text path (committed history + render use).
- **`render.py` typed-text pagination / `PARA_SPACE_UNIT` / `TYPED_TEXT_BLANK_H` / `TYPED_TEXT_PAGE_PAD`
  / `_text_box_layout` frame_midpoints branch**: these are **render heuristics/calibrations**, not decoded
  format — see §5.
- **`page.py` `_text_box_frame_midpoints` / `scan_attachment_placements`**: previous-block RE (frame
  midpoints validated against bbox center; attachment property bags generalising sticky-notes).

---

## 4. Commands run this round (all pass)

```bash
.venv/bin/python -m py_compile pysdocx/*.py                     # COMPILE OK
.venv/bin/python -m pysdocx inventory samples                   # unknown_bits empty; profiles listed
.venv/bin/python -m pysdocx inventory samples --json > docs/FORMAT-COVERAGE-INVENTORY.json
.venv/bin/python -m pysdocx objects samples/OnlyHighlighterBlack_260630_131753.sdocx --detail
.venv/bin/python -m pysdocx render samples/OnlyTextTypeWritten_squared_260703_013624.sdocx /tmp/regr2   # 3 PNGs
.venv/bin/python -m pysdocx text samples/OnlyTextTypeWritten_squared_260703_013624.sdocx                # page 2 text_boxes=3
```
Cross-checks (scratchpad scripts): object-header `unknown_bits` empty corpus-wide; `ext_block`
width/height match **1690/1690**; `extra_key_stroke_shape` byte map **40/40**. **Render regression
guard passes** — the squared sample still renders 3 pages / 3 text boxes, no content moved (this round
touched no render code).

### New/changed CLI surfaces
- `pysdocx inventory [paths…] [--json]` — corpus coverage matrix + object/note/attachment profiles (prev
  block; JSON regenerated this round).
- `pysdocx text … --layout-debug` — prev block; prints text-box anchor/wrap/lines (render **hypothesis**,
  not decoded).
- `pysdocx objects … --detail` — this round adds `header_features` / `ext_block` lines.

---

## 5. Decoded-fact vs render-heuristic (keep separate!)

- **Decoded (trust):** field_flags bits & sizes (§2a), `ext_block` page dims (§2b), extra_key byte map
  (§2c), flags-field invariant (§2d), meta tables flag (§2e), `frame_midpoints` geometry (validated vs
  bbox center), attachment property bags, pageIdInfo↔tail-hash link.
- **Heuristic / visual calibration (do NOT treat as format):** `PARA_SPACE_UNIT`, `TYPED_TEXT_BLANK_H`,
  `TYPED_TEXT_PAGE_PAD`, `TYPED_TEXT_LINE_H`, typed-text page-placement, `_text_box_layout` line-breaking,
  the "move whole styled run to next line" rule, `--layout-debug` output. Calibrated against
  `samples/OnlyTextTypeWritten_squared_260703_013624.sdocx` (GT photo in its sibling folder) and the
  images GT (`samples/OnlyImages_260702_190147/…`).

---

## 6. Known weaknesses / bugs still open

1. **`seq`/`counter` semantics unresolved.** The overclaim is fixed, and inventory now reports per-file
   `seq`/`counter` summaries. Current facts: `seq` is near-constant per note and not always monotonic;
   `counter` repeats and often groups related objects, but no clean semantic is promoted yet.
2. **Rotated text-box inner layout is still heuristic.** Geometry (`frame_midpoints`) is decoded.
   Follow-up Codex visual check preserved the 90° three-column wrap against GT and added an
   inner-wrap inset only for non-vertical rotated boxes, fixing the 16° sample's line break. No
   separate decoded padding field has been found.
3. **extra_key trailing u32 = 1**: decoded as constant, but flag-vs-count can't be disambiguated (never
   varies).
4. **note.note beyond typed-text/tables/title/voice**: still largely unmapped (agent-3 for this produced
   nothing — session limit).

---

## 7. Recommended restart point for Codex

In priority order:

1. **Continue the `seq`/`counter` correlation only if new samples appear** or if we decide to analyze
   copied-object lineage more deeply. Current inventory makes the known limits reproducible, but corpus
   evidence is not enough for a stronger semantic.
2. **note.note structural map** (agent-3's unfinished lead): enumerate every ASCII key & TLV record in
   `note.note` across the corpus; decode the currently-opaque tail fields (`tail_hash_block.prefix_u32`,
   hash meaning, `pen_preload_path.param_hint`, voice_clip `post_u32`, `tail_sentinel` bytes). Same
   grounded discipline: promote only zero-counterexample facts.
3. Only after the above: revisit the 90° text-box wrap (heuristic, lower RE value).
4. **Checkpoint commit** the whole tree (prev Codex block + this round) once §7.1 lands — currently
   nothing is committed.

Discipline to keep (per project norms): iterate in `pysdocx` first (port to Rust only at checkpoints);
promote a byte only with zero corpus counterexamples; mark every heuristic/magic-number explicitly; never
commit without the user's explicit OK.

---

## 8. Follow-up after this handoff — note.note tail map

Codex continued §7.2 and landed a conservative `note.note` tail inventory:

- `pen_preload_path` is now decoded as `u16 char_len + UTF-16LE path`, not as a null-terminated UTF-16
  string. This fixes the false leading slash and the occasional CJK-looking garbage suffix after paths
  such as `InkPen2`.
- Preload paths increased from `19` to `38` corpus hits because the old scanner missed path fields whose
  length byte was not being treated as a length prefix.
- Inventory now records preload path counts, nearby digit/semicolon `param_hint` strings, hash prefixes,
  voice `post_u32`, and byte-level tail coverage.
- Follow-up RE classifies bounded tail gap records: `pen_preload_prelude`,
  `pen_preload_prelude_raw`, `pen_style_tail`, `voice_clip_header`, `voice_clip_post`, and
  `tail_post_hash_u32`. Localized Italian voice labels (`Voce N`) are now recognized too.
- Current corpus tail coverage: `5938` known bytes / `0` unknown bytes (`100%` structurally covered).
- Remaining honest unknowns: full preload surrounding record semantics, param-hint semantics,
  `pen_style_tail.raw_u32`, trailing post-hash 4-byte values on some notes, and
  `voice_clip.post_u32` semantics.
