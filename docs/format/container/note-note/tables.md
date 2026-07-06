# `note.note` → tables

Table content lives in `note.note` (not in the `.page` ink tree). Decoded
**by marker**, so it is documented here rather than in a `.ksy`.

- **Reference parser:** `parse_tables` / `_cell_style` in
  [`pysdocx/note.py`](../../../../pysdocx/note.py).
- **Presence flag:** `note.note` `meta_flags` bit `0x2000` = has-tables (set on
  exactly the 2 table-bearing corpus notes). See
  [the header page](./README.md#meta_flags).
- **Status:** cell text + grid + basic rich text **Decoded (Marker)**; a full
  schema of every table block is **Unknown**.

## Cell marker — Decoded

Each cell is preceded by a 10-byte marker, immediately followed by the cell's
UTF-16LE text:

```
06 00 <u16 kind> 00 00 <u32 char_count>   marker (10 bytes)
<char_count * 2 bytes UTF-16LE>           cell text
```

Observed `kind` values: `0x8d`, `0x95`, `0xcd`. The cell's bottom-left corner in
page coordinates is the `f64` pair located **before** the marker: x at
`marker - 16`, y at `marker - 8`. Clustering these anchors reconstructs the row
and column grid.

## Cell rich text — Decoded

A cell's styling follows immediately after its own text as a **local** run of the
exact same TLV markers used by the [typed-text path](./typed-text.md#inline-style-runs--decoded-tlv),
but scoped to the cell: `start = 0`, `end = char_count` (the cell's own length),
not document-wide offsets. Only runs matching the cell exactly (`start == 0 and
end == char_count`) are accepted, so a run overrunning into the next cell cannot
be mis-attributed. Bold/italic/underline, color, and font size are read this way;
a plain cell simply carries only the default color+font runs.

## What is Unknown

- The full block-level table schema (borders, merged cells, per-column widths as
  stored fields rather than reconstructed from anchors).
- Whether `kind` encodes a table style/type beyond distinguishing cell records.
