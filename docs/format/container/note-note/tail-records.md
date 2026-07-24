# `note.note` → tail region (flex fields)

The region of `note.note` beginning at the header's `flex_offset` (alias
`offset_to_data`). Historically this was decoded bottom-up as a sequence of
marker-scanned "tail records"; it is now **Decoded top-down** as the flex
fields gated by `field_flags` — see the field table in [README](./README.md).
Corpus byte-coverage of the tail is 100% with exact boundaries (the sequential
parse must land on the trailing hash).

- **Formal spec:** [`spec/ksy/sdocx_note.ksy`](../../../../spec/ksy/sdocx_note.ksy).
- **Reference parser:** `parse_note_doc` in
  [`pysdocx/note_doc.py`](../../../../pysdocx/note_doc.py).
- **Legacy scans (still used by the renderer):** `scan_note_tail_records` /
  `annotate_note_tail_with_page_id_info` in
  [`pysdocx/note.py`](../../../../pysdocx/note.py), cross-checked against the
  structural parse by
  [`spec/tools/analyze_note_doc.py`](../../../../spec/tools/analyze_note_doc.py).

## Legacy record kinds → structural fields

Every marker-scanned record kind is explained by a flex field:

| Legacy scan kind | Structural decode |
|---|---|
| `tail_sentinel` (16 bytes `00000000 ffffffff 00000000 00000000`) | the first three flex fields: `last_edited_page_index = 0` (u32) + `last_edited_page_image_id = -1` (i32) + `last_edited_page_time_us = 0` (i64) |
| `pen_preload_path` (UTF-16 resource paths) | `pen_info.name` (in `last_pen_info` / `compatible_last_pen_info`) and `string_registry` values |
| preload parameter hints (`8;`, `14;`, `18;0;100;`, …) | `pen_info.advanced_settings` and `string_registry` values — the registry pairs each pen resource name with its parameter string |
| `pen_preload_prelude` / `_raw` | the fixed pen-record fields around the strings (`size` f32, `color` ARGB, `is_curvable`, `is_eraser_enabled`, `size_level`, `particle_density`, `ui_color_hsv`, `ui_color_info`, and in the full record `particle_size`, `is_fixed_width`, optional `is_fixed_opacity` / `is_auto_size_enabled` / `fit_ratio`) |
| `pen_style_tail` (leading f32 width + ARGB) | `pen_info.size` + `pen_info.color` |
| `voice_clip` / `_header` / `_post` | `voice_data` records: `[u32 size][u32 file_id][short-utf16 name][short-utf16 duration_str][i64 created_time_ms][u32 event_count × (u32 action, i64 time_us)][i64 precise_duration_ms]`; `file_id` is the `.m4a` mediaInfo index, `action` is 0 none / 1 start / 2 pause / 3 resume / 4 stop, `precise_duration_ms` is the previously scanned actual-duration candidate. **Correction (2026-07-24):** `created_time_ms` was previously mislabeled `created_time_us` by analogy with the note-header timestamps — it is actually epoch **milliseconds**, unlike the sibling `events[].time_us` (genuine microseconds) and every other `_us` field in the format. Verified on the 2/2 corpus samples carrying voice clips: the raw value is 13 digits and only resolves to a plausible date (matching the sample's own export date) when read as epoch millis; read as micros and converted again for display, it collapses to a 1970-01-2x date — exactly the bug the user spotted in OpenSdocx's audio player. |
| `tail_hash_block.prefix_u32` (two u32s before the hash) | `fixed_text_direction` + `fixed_background_theme` (both `2` = default on the corpus) — the last two flex fields before the trailing hash |
| `tail_hash_block` boundary variants / `tail_post_hash_u32` | scan artifacts: the hash is always exactly `note.note[-32:]`; the "shifted" candidate windows and the copied post-hash u32 were mis-anchored heuristics, superseded by the exact structural boundary |

All of the above validate with zero counterexamples on the corpus
(`analyze_note_doc.py`: voice names/durations/file-ids/precise-ms 2/2, pen
names 11/11 against the preload scans, string registry parsed on 11/11 files
that set bit 10).

## Still Unknown

- **`pre_flex_gap`** (before the flex fields, not strictly part of them): 0 or
  8 bytes; when 8, a u32 pair `(width, round(width*sqrt(2)))` — an
  A4-proportioned default-page-size candidate. It does not always match the
  real `.page` sizes (single-scroll notes differ), so it stays Unknown.
- **Semantics of pen numeric fields** beyond their names (`size_level`,
  `particle_density`, `ui_color_info`) — named from `sdocx2pdf`, values
  bounded, effect untested.
- **Unexercised flex fields** (corpus 0/14): `app_name`, `app_version`,
  `author_info`, `latitude_longitude`, `template_uri`,
  `compatible_last_pen_info`, `attached_files`, `server_check_point`,
  `fixed_font`, `text_summarisation`, `stroke_group_size`,
  `app_custom_data` — structurally modeled, need targeted samples.
