# SDOCX Format Notes

> **One-time snapshot — not maintained live.** These notes were extracted from the
> markdown cells of `notebooks/03_ink.ipynb`. They originate from the forked
> reverse-engineering repo plus our own corrections. For the fuller, more current
> write-up see [`samsung-notes-format/RESEARCH.md`](../samsung-notes-format/RESEARCH.md).
> The authoritative, executable behaviour lives in the `pysdocx` parser
> (`container.py`, `page.py`, `note.py`, `ink.py`) and the renderer (`render.py`).

## Ink properties

Each stroke's delta data blob contains more than just coordinates. After the coordinate
deltas, there's a **trailing section** with per-point attribute channels (pressure,
timestamp, tilt) and per-stroke properties (color, pen width).

## Trailing data structure

Each stroke's data blob has two regions:

```
+------------------------+----------------------------------------------+
|   Coordinate Deltas    |  Trailing: channels + stroke properties      |
|   (4 bytes per point)  |  [4B gap] [pressure] [time] [tilt] [color+w] |
+------------------------+----------------------------------------------+
```

The trailing section starts **4 bytes** after the coordinate data ends. It contains
**four per-point channels**, each encoded as sign-magnitude byte pairs (same encoding
as coordinates, but 1D — no x/y interleaving), followed by **per-stroke color and pen
width** at the very end.

## Per-stroke color, width, tool, and intensity

Color, pen tool, and pen width are stored at the **end** of the data blob (within the last
~100 bytes — search only the tail, not the whole blob, or you'll occasionally match this same
6-byte shape by coincidence inside the per-point channel data on long, low-variance strokes),
preceded by a 6-byte marker:

```
02 00 TT 00 00 00
```

`TT` encodes **which pen tool** drew the stroke: `tool_id = (TT - 1) / 2`. This is **not a
single global registry** — confirmed on two ground-truth files (one stroke/size per tool,
left to right):

- `samples/OnlyPensBlacksize10_*.sdocx`: `0`=pen, `1`=fountain pen, `2`=calligraphy pen,
  `3`=pencil, `4`=calligraphy brush (all odd `TT`).
- `samples/OnlyHighlighterBlack_*.sdocx`: "highlighter" reuses `TT=1` (same as "pen"!),
  "marker pen" uses `TT=4` (even). The two "straight-line" (ruler-mode) variants use a
  **short-form marker** without the leading `02 00`: `[TT 00 00 00] [BGRA] [f32 width]`.

After the marker, the layout is either `[BGRA][f32 width]` (explicit color) or `[f32 width]`
directly (default ink, no color):

- **alpha (4th color byte) `= 0xFF`** → full-opacity color, then width.
- **leading 4 bytes are a sane width float** → no color, width stored directly (default ink).
- **otherwise** → reduced-opacity color, where the **alpha byte is the pen's "intensità"
  (opacity) slider**: e.g. pencil at intensity 100 = alpha `0xFF`, intensity 50 = `0x80`,
  intensity 0 = `0x03` (low but non-zero — still faintly visible, as in the app). Decoded into
  the per-stroke `intensity` field (0-255).

Ink-pen-category tools also carry a 12-byte block after the width (`[u32 = 2·tool_id][width
repeated]`) that highlighter/marker tools lack — this is the `tapered` flag (pressure-sensitive
nib vs. flat felt tip).

## Per-point pressure

The first per-point channel encodes **pen pressure**. Like coordinates, it uses
sign-magnitude byte pairs — but these are **1D deltas** (not x/y pairs).

Each pair: `(magnitude, sign_flag)` where `0x00` = positive, `0x80` = negative.

The cumulative sum of pressure deltas gives the actual raw pressure at each point,
ranging **0–~1400**, with a characteristic ramp-up at pen-down and sharp drop at
pen-lift. `pysdocx.decode_trailing` (run inside `parse_page`) normalizes this to
**0.0–1.0** and stores it on each stroke as `pressures`.

## All per-point channels

After the 4-byte gap, there are **four consecutive channels**, each with `n_points`
sign-magnitude delta pairs:

| Channel | Offset from trail start | Content |
|---------|------------------------|---------|
| 0 | `0` | Pressure (0–1400) |
| 1 | `n_points x 2` | Timestamp (monotonic) |
| 2 | `n_points x 4` | Tilt X |
| 3 | `n_points x 6` | Tilt Y |

## Rendering

Combining everything: coordinates from delta decoding, per-stroke color from the
color marker, and per-point pressure for variable stroke width.

Width formula:

```
base_width  = pen_width / 2.5
segment_width = base_width x (0.3 + 0.7 x normalized_pressure)
```

Where `normalized_pressure = clamp(cumulative_pressure / 1400, 0, 1)`.

## Complete SDOCX format summary

### Container (ZIP)

| File | Content |
|------|---------|
| `end_tag.bin` | Timestamps (i64 ms epoch), `"Document for S-Pen SDK"` |
| `pageIdInfo.dat` | Page UUID (UTF-16LE) + 2 x 32-byte hashes |
| `media/mediaInfo.dat` | Media filename + SHA-256 + `EOFX` |
| `note.note` | Title, pen tools, background color, dimensions |
| `media/*.spi` | Page thumbnail (Samsung proprietary) |
| `<uuid>.page` | Stroke data (see below) |

### Page file (`.page`)

**Header:**

| Offset | Type | Field |
|--------|------|-------|
| `0x00` | u32 | Base offset (`base`) |
| `0x16` | u32 | Page width |
| `0x1A` | u32 | Page height |
| `0x26` | u16 | UUID length (chars) |
| `0x28` | UTF-16LE | Page UUID |
| `0x80` | 4 x f64 | Content bounding box |
| `base + 0x66` | u32 | Stroke count |

**Stroke records** (starting at `base + 0xB5`, sequential):

| Part | Bytes | Format |
|------|-------|--------|
| Bounding box | 32 | 4 x f64 |
| Metadata | 41 | byte 21: u32 data_len; byte 39: u16 n_points |
| Start point | 16 | 2 x f64 |
| Delta data | data_len | See below |
| Inter-stroke | 71 | UUID + timestamp |

**Delta data layout:**

| Region | Encoding | Description |
|--------|----------|-------------|
| Coordinates | 4-byte groups: `[dx_mag, dx_sign, dy_mag, dy_sign]` | `0x00`=+, `0x80`=-, scale x 1/32 |
| 4-byte gap | — | Separator |
| Pressure | 2-byte pairs x n_points | Sign-mag deltas, cumsum 0–1400 |
| Timestamp | 2-byte pairs x n_points | Sign-mag deltas, monotonic |
| Tilt X | 2-byte pairs x n_points | Sign-mag deltas |
| Tilt Y | 2-byte pairs x n_points | Sign-mag deltas |
| Color marker | `02 00 01 00 00 00` | Precedes color/width |
| Color (optional) | 4 bytes BGRA | Present if 4th byte = `0xFF` |
| Pen width | f32 | Follows color or marker directly |

**Footer:** 26-byte ASCII `"Page for SAMSUNG S-Pen SDK"`

### Base offset

The first u32 (`base`) determines where stroke fields are located. Simple handwritten
files have `base = 0xE3` (227). Files with embedded media (PDF, images) have a larger
base to accommodate object descriptor records in the header.

### Sign-magnitude encoding

Used for both coordinate deltas and per-point channels:

- Each value is a 2-byte pair: `(magnitude, sign_flag)`
- `sign_flag = 0x00`: positive (`+magnitude`)
- `sign_flag = 0x80`: negative (`-magnitude`)
- Bit 7 of the sign byte acts as the sign bit
