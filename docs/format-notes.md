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
| `end_tag.bin` | Footer metadata: size, format, timestamps, raw fields, `"Document for S-Pen SDK"` |
| `pageIdInfo.dat` | Page UUID (UTF-16LE) + 2 x 32-byte hashes |
| `media/mediaInfo.dat` | Media manifest: index, filename, SHA-256, raw tail, `EOFX` |
| `note.note` | Title, pen tools, background color, dimensions |
| `media/*.spi` | Page thumbnail (Samsung proprietary) |
| `<uuid>.page` | Stroke data (see below) |

### Page file (`.page`)

The current parser treats `.page` as a real tree:

```
page header
  layer list
    object entry: raw_type + child_count + blob_size
      common object header
      type-specific payload
      children, for container-like objects
```

This replaced the earlier "flat stroke record stream" model. In simple handwritten files the
layer object count equals the number of strokes, so the old parser appeared to work. Mixed pages
contain shapes/images/drawings/text-like objects interleaved with strokes; using object `blob_size`
is the deterministic way to advance to the next record.

**Page header:**

| Offset | Type | Field |
|--------|------|-------|
| `0x00` | u32 | Layer-list base offset (`base`) |
| `0x16` | u32 | Page width |
| `0x1A` | u32 | Page height |
| `0x26` | u16 | UUID length (chars) |
| `0x28` | UTF-16LE | Page UUID |
| `0x80` | 4 x f64 | Content bounding box |

At `base`, the layer list starts with:

| Offset from `base` | Type | Field |
|--------------------|------|-------|
| `0x00` | u16 | Layer count |
| `0x02` | u16 | Current layer index |

Each layer then carries flags, optional UUID/mtime fields, an object count, object entries, and a
32-byte hash. In the common samples with `content_flags = 0x18`, the layer UUID and modified time
are present before the object count.

**Object entry:**

| Part | Bytes | Format |
|------|-------|--------|
| Raw object type | 1 | Build/version-dependent byte |
| Child count | 2 | i16 |
| Blob size | 4 | u32, exact number of bytes in the object blob |
| Object blob | `blob_size` | Common object header + payload |

**Common object header** (at the start of the object blob):

| Field | Type / notes |
|-------|--------------|
| Total header size | u32 (`121` for normal strokes, `122` for many non-stroke objects) |
| Data type | i16, observed `0` |
| Variable data offset | u32, observed `105` in current samples |
| Flag bytes | length byte + flags |
| Field flags | length byte + flags |
| Format version | u32, observed `4000` |
| UUID | i16 byte length + UTF-8 bytes |
| Modified time | i64 |
| Bounding box | 4 x f64 |
| Timestamp | u32 |
| Resizable | u8/bool |
| Attributes/payload | starts after the common fields; exact layout depends on object type |

**Observed raw object types in our samples** (do not copy the external project's table blindly):

| Raw | Classified as | Evidence |
|-----|---------------|----------|
| `1` | Stroke | Stroke payload at object bbox offset; field flags `0x6000` / variants |
| `2` | Text box | `Associationpages...`, `OnlyTextTypeWritten...`; UTF-16 text payload with bbox in common header |
| `3` | Imported image | `01 00 04 20` marker; newer samples carry the media index after `06 00 3e 00 00 00 02 00`, older samples also match a u16 fallback 6 bytes before marker |
| `7` | Shape | Marker-based shape payloads in benchmark and shape samples |
| `8` | Shape variant | Shape/line/arrow objects in shape samples |
| `14` | Drawing | Benchmark freehand drawing; `05 00 00 00 <u32 media_index> <hash>` |

The parser classifies objects primarily by payload markers, not by raw byte alone, because raw
values vary between sample families.

**Inserted-object payload geometry wrapper** (validated on shape/image/text-box objects):

After the common object header, non-stroke visual objects observed in the current corpus carry:

```text
0   u32 L0
+4  u16 tag = 6
+6  u32 L1
+10 01 00 01 0c
+14 u32 point_count
+18 point_count x (f64 x, f64 y)
```

Current corpus coverage: 412 decoded wrappers (`shape=390`, `image=15`, `text_box=7`). Marker equations:

| Family | Equation |
|--------|----------|
| Image marker `01 00 04 20` | `marker == total_size + L0 + 10 == total_size + L1 + 49` |
| Shape marker `01 04 04 01 00 00 00` | same as image, on marker-based shapes |
| Text-box UTF-16 marker | `marker == total_size + L1 + 172` (`L0` relation differs by +123) |

Images and text boxes use the 4 decoded points as frame geometry. Shape centroid relation is not a
global invariant across every shape variant, so the wrapper is structural while per-shape semantics are
still partly variant-specific.

Current shape point-role map:

| Role | Shape families |
|------|----------------|
| `outline_vertices` | ellipse, hexagon, rhombus, pentagon |
| `frame_edge_midpoints` | rectangle, trapezoid, cross, rounded-rect |
| `vertices_with_edge_midpoints` | triangle |
| `outer_vertices` | star |
| `freeform_vertices` | freeform 88/89 |
| `bezier_control_points` | smooth freeform, heart |
| `shaft_endpoints` | markerless line/arrow |

This role is exposed as `payload_geometry_role` on parsed shape dictionaries when parsing from the
object tree.

**Stroke object payload** (inside a raw type `1` object):

The stored object bbox starts at blob offset `68`; the stroke decoder reads from there. The
common header `total_size` determines `extra_len`:

| Header total | Meaning |
|--------------|---------|
| `121` | Normal stroke, no extra attribute block |
| `137` | 16-byte extra block |
| `169` | 48-byte extra block, straight-line synthetic/highlighter cases |
| `173` | 52-byte extra block |

After `bbox + metadata + start point`, the stroke delta data follows.

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

The first u32 (`base`) points to the layer list, not directly to stroke data. It varies with
the page header shape (`0x90`, `0xE7`, `0x118`, `0x1C7`, ... in current samples). Older notes in
this repo treated `base + 0x66` as a stroke count; for the common one-layer header this is
actually where the layer object count lands. On all-stroke pages those counts happen to match,
but mixed pages prove they are different concepts.

### Sign-magnitude encoding

Used for both coordinate deltas and per-point channels:

- Each value is a 2-byte pair: `(magnitude, sign_flag)`
- `sign_flag = 0x00`: positive (`+magnitude`)
- `sign_flag = 0x80`: negative (`-magnitude`)
- Bit 7 of the sign byte acts as the sign bit
