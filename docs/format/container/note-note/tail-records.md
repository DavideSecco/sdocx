# `note.note` → tail records

The region of `note.note` beginning at the header's `offset_to_data`. It is a
sequence of small records (a sentinel, a hash block, pen-preload paths and
their preludes, pen-style blocks, and voice-clip records) located by **markers**,
not fixed offsets — so it is documented here, not in a `.ksy`.

- **Reference parser:** `scan_note_tail_records` /
  `annotate_note_tail_with_page_id_info` in
  [`pysdocx/note.py`](../../../../pysdocx/note.py).
- **Status:** boundaries **Structural**; several fields **Semantic**; residual
  fields **Unknown**. Corpus byte-coverage of the tail is **100% structurally
  accounted** (no unexplained bytes), but "accounted" ≠ "semantically named".

## Record kinds — corpus counts

| Kind | Count | Status |
|---|---|---|
| `tail_sentinel` | 13 | starts exactly at `offset_to_data` on 13/13 |
| `tail_hash_block` | 13 | one per note; linked to `pageIdInfo.dat` head |
| `pen_preload_path` | 38 | `u16 char_len + UTF-16LE` resource path |
| `pen_preload_prelude` / `_raw` | 24 / 13 | bounded blocks before paths |
| `pen_style_tail` | 10 | leading `f32` width + ARGB color + optional param |
| `voice_clip` / `_header` / `_post` | 2 / 2 / 2 | audio metadata (2 audio notes) |
| `tail_post_hash_u32` | 3 | 4 bytes after some hash blocks |

## Decoded / Semantic

- **`tail_sentinel`** — the fixed pattern `00000000 ffffffff 0000000000000000`
  marks the start of the tail; it begins exactly at `offset_to_data` on 13/13.
- **`tail_hash_block`** — appears once per note and is structurally linked to the
  `pageIdInfo.dat` head hash (10 exact + 3 shifted matches on the corpus).
- **`pen_preload_path`** — decoded as `u16 char_len + UTF-16LE path`, e.g.
  `com.samsung.android.sdk.pen.pen.preload.InkPen2`. Reading it as a
  length-prefixed string (not null-terminated) fixed a false leading slash and a
  CJK-looking suffix, and raised the corpus hit count from 19 to 38.
- **`pen_style_tail`** — a recurring block with a leading `f32` pen width and an
  ARGB color, plus an optional digit/semicolon parameter string.
- **Voice linkage** — `voice_clip_header.raw_u32[3]` matches the `.m4a`
  `mediaInfo.dat` media index on both audio samples; `voice_clip_post` exposes an
  actual-duration-ms candidate (`5760`, `12053`). Promoted as **diagnostic**
  linkage, not a complete audio schema.

## Unknown (bounded, not named)

- Exact semantics of the raw fields immediately around preload paths, and of the
  preload parameter hints (`8;`, `14;`, `18;0;100;`, …) — these do **not** map
  one-to-one to pen tool names on the current corpus.
- `pen_style_tail.param` / `pen_style_tail.raw_u32`.
- The 4-byte `tail_post_hash_u32` values after some hash blocks (they match
  `note.note[-4:]` on the 3 shifted samples — likely a copy of the trailing
  bytes, not a standalone checksum).
- `voice_clip.post_u32` semantics beyond the duration candidate.
- The meaning of the `tail_hash_block` hash itself.

These stay Unknown deliberately: the corpus bounds them structurally but cannot
yet isolate their meaning without samples that vary one variable at a time.
