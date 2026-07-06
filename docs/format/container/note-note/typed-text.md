# `note.note` → typed rich text

The keyboard-typed body text of a note and its styling. Decoded **procedurally**
(by scanning content markers and TLV style runs), not as a fixed layout, so it
lives here rather than in a `.ksy`.

- **Reference parser:** `parse_typed_text` / `_find_text_field` / `_style_runs` /
  `_paragraph_metadata` in [`pysdocx/note.py`](../../../../pysdocx/note.py).
- **Status:** text + inline styling **Decoded (Marker)**; page placement in the
  renderer is **Heuristic** (see [`../../heuristics.md`](../../heuristics.md)).

## Finding the body text — Marker

The body is a UTF-16LE run inside `note.note`, but it is **not** simply "the
longest printable UTF-16 run": on drawing-only notes that heuristic locks onto
the pen-preload resource string. It is located instead by a **`u32` char-count
header immediately preceding the field** whose value equals the field length
(exact or ±1 for a terminator). Validating that length header (`_find_text_field`,
tolerance 2) is what distinguishes real body text from incidental UTF-16 — it
inspects structure, not content, so it also holds for genuine CJK text. On
drawing-only notes this correctly yields no text (blank page, no mojibake).

The leading pad/newlines are stripped from `text`; all run offsets below are
rebased to the stripped body.

## Inline style runs — Decoded (TLV)

Character-range styling is a series of TLV records. Each record:

```
18 00 <tag> 00   marker (tag selects the property)
<pad>
u32 start        first character index (inclusive)
u32 end          last character index (exclusive)
u32 value
u32 enabled      boolean flag, OR the payload for color/font
```

Tags and how the trailing `u32` is read:

| Property | `tag` | Trailing `u32` meaning |
|---|---|---|
| Bold / Italic / Underline | bold/italic/underline | `enabled` ∈ {0,1} |
| Strikethrough | `14 00 14 00` (4-byte prefix) | `enabled` ∈ {0,1} |
| Color | color tag | `0xAARRGGBB` (alpha 0xFF) |
| Highlight | highlight tag | `0xAARRGGBB` (alpha 0xFF) |
| Font size | font tag | `f32` bit pattern (px, 4.0–200.0) |

Samsung emits a matching "off" run after each "on" run; the parser keeps only
`enabled == 1` runs. **Strikethrough needs extra care:** its 4-byte prefix is
short enough to collide with unrelated binary data, so a run is only accepted
when it forms the clean on/off pairing (an `enabled==1` run whose `end` equals
the `start` of a following `enabled==0` run). This rejects the observed stray
collisions (e.g. `enabled=30465`).

## Paragraph metadata — Decoded

Paragraph-level attributes are indexed **by paragraph number** (aligned with
`text.split("\n")`), not by character offset:

- `14 00 <tag> 00` records — alignment, indent, line-spacing, and heading/body
  style. Tags `0x08` = space-before and `0x09` = space-after carry a `float` in
  the `value` field (present only on styled paragraphs); `0x04` = line-spacing
  uses the `enabled` field instead.
- `1c 00 05 00` records — numbered / bullet / todo list prefixes and the
  todo checked state.

## What is Decoded vs Heuristic

- **Decoded:** body-text location (length-header), all inline style runs above,
  paragraph alignment/indent/line-spacing/heading/list/todo metadata.
- **Heuristic (renderer, not format):** how the decoded text is laid out and
  paginated onto pages — `PARA_SPACE_UNIT`, `TYPED_TEXT_BLANK_H`, line height,
  page placement. These are calibrated against ground-truth photos and are
  documented in [`../../heuristics.md`](../../heuristics.md); they are **not**
  properties of the file.
