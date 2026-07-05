# Text Box Rotation RE Notes

Checkpoint gathered on branch state:

```text
febc3cd feat(pysdocx): heading spacing and typed-text pagination
```

Context:

- Sample: `samples/OnlyTextTypeWritten_squared_260703_013624.sdocx`
- Page: 2 (`a48f4f92`)
- Objects on page: exactly 3 text boxes
  - object 0: horizontal
  - object 1: mildly rotated (`16°`)
  - object 2: vertical (`90°`)

## Parsed Object/Header Facts

From `python -m pysdocx objects ... --detail`:

- Object 0
  - `object_idx=0`
  - `bbox=(71.0,1503.2)-(1133.8,1737.2)`
  - `header_total=121`
  - `field_flags=0x6000`
- Object 1
  - `object_idx=1`
  - `bbox=(71.0,1635.2)-(556.3,1869.2)`
  - `header_total=141`
  - `field_flags=0x46001`
- Object 2
  - `object_idx=2`
  - `bbox=(979.1,1797.3)-(1650.1,2055.6)`
  - `header_total=141`
  - `field_flags=0x46001`

Immediate observation:

- The rotated boxes (`16°`, `90°`) share `header_total=141` and `field_flags=0x46001`.
- The plain horizontal box uses `header_total=121` and `field_flags=0x6000`.
- So far, the cleanest decoded difference is:
  - rotation gate bit present on rotated boxes
  - longer common-object header on rotated boxes

## Angle Field

The parser reads angle from `OBJECT_BASE_HEADER_LEN == 105` when `field_flags & 0x1`.

Observed raw f32 values at that offset:

- object 0: garbage `-6627412992.0` with `field_flags=0x6000`
- object 1: `16.0`
- object 2: `90.0`

Conclusion:

- The current angle decode still looks correct for text boxes, same as images.
- No additional angle-adjacent field obviously explains text flow or wrap width yet.

## Text Payload Structure

Reliable parsed offsets:

- object 0
  - `object_off=0x151`
  - `text_off=0x2e2`
  - `text_off - object_off = 0x191`
- object 1
  - `object_off=0x435`
  - `text_off=0x5da`
  - `text_off - object_off = 0x1a5`
- object 2
  - `object_off=0x711`
  - `text_off=0x8b6`
  - `text_off - object_off = 0x1a5`

Observation:

- The rotated boxes again match each other (`0x1a5`), while the simple horizontal box is shorter
  (`0x191`).
- This may just reflect the longer rotated-object header, not extra text-layout metadata.

## Rich-Text Local Runs

Parsed local styling:

- object 0
  - color run only
  - font-size run only
- object 1
  - color run only
  - font-size run only
- object 2
  - color run
  - font-size run
  - bold run: `37..47`
  - italic run: `52..59`

Conclusion:

- Nothing yet suggests the rotated text-box layout bug comes from a different rich-text run
  structure. The vertical box simply has more styling, but the local text format looks like the
  same family.

## Current Renderer Hypothesis

From `python -m pysdocx text ... --layout-debug` after switching the renderer to the decoded
frame-midpoint geometry path and adding the current inner-wrap heuristic:

Object 1 (`16°`):

- `bbox_inner=469.3 x 218.0`
- `anchor=(112.7,1572.9)`
- `wrap=449.3`
- logical wrapped lines:
  1. `testo dentro una `
  2. `casella di testo su `
  3. `2 righe inclinata`

This is a renderer heuristic: `frame_midpoints` provide the outer frame, then the renderer shrinks
the logical wrap width by `18.0` page units per side for non-vertical rotated boxes. That makes the
line break match the current GT better; no separate decoded padding field has been found.

Object 2 (`90°`):

- `bbox_inner=655.1 x 242.3`
- `anchor=(1443.8,1590.9)`
- `wrap=671.1`
- logical wrapped lines:
  1. `testo dentro una casella di `
  2. `testo in grassetto e in `
  3. `corsivo ruotato di 90 gradi`

Important:

- The anchor and wrap width now come from decoded frame geometry, not the old bbox-only
  vertical-box heuristic.
- Near-vertical text boxes deliberately keep the full projected wrap width; shrinking it moved
  `di` to the next logical line and visibly disagreed with the current GT.
- The line breaks are still a renderer hypothesis layered on top of that geometry.
- This is much closer to the GT, but should still be treated as provisional until validated on
  more rotated samples.

## What Did NOT Emerge Today

- No obvious decoded “logical text width” field separate from bbox.
- No obvious decoded padding/inset field for vertical boxes.
- No obvious decoded per-line break metadata.
- No evidence yet that the local rich-text run block itself changes shape for rotated boxes.

## Stronger Geometric Lead

Comparing the two rotated boxes byte-for-byte in the range:

```text
header_total .. text_off
```

showed the same overall structure but different values at very regular positions.

When the pre-text region is interpreted as `f64` values starting at a shifted offset (`+0x12`
relative to `header_total`), both rotated boxes produce 4 plausible `(x, y)` pairs:

- object 1 (`16°`)
  - `(345.9163, 1639.7550)`
  - `(546.9329, 1819.1106)`
  - `(281.4171, 1864.6903)`
  - `(80.4005, 1685.3347)`
- object 2 (`90°`)
  - `(1443.7500, 1926.4719)`
  - `(1314.5831, 2261.9990)`
  - `(1185.4163, 1926.4719)`
  - `(1314.5831, 1590.9449)`

Why this matters:

- These are page-scale coordinates, not tiny flags or style values.
- They look like a stable 4-point geometry payload for rotated text boxes.
- For the `90°` box, the 4 points form a symmetric diamond/cross-like set centered near the box,
  which is exactly the kind of structure that could encode orientation, handles, or a logical text
  frame distinct from the axis-aligned bbox.

Extra confirmation:

- For both rotated boxes, the average of those 4 points is EXACTLY the bbox center.
- Their radii from that center are:
  - object 1: `117.0` and `242.6667`
  - object 2: `129.1668` and `335.5271`
- These match:
  - `bbox_h / 2`
  - `bbox_w / 2`

So the best current interpretation is:

- the pre-text geometry block stores the 4 edge-midpoints of the rotated text-box frame
- i.e. the same kind of “oriented midpoint geometry” Samsung uses elsewhere for rotated objects
- not a separate decoded wrap width or padding field by itself

At a later stable shifted offset (`+0x97` relative to `header_total` for the rotated boxes), the
same region also contains the decoded bbox coordinates themselves:

- object 1: `71.0, 1635.2227, 556.3334, 1869.2227`
- object 2: `979.0566, 1797.3049, 1650.1096, 2055.6387`

Interpretation:

- The rotated-object payload appears to store BOTH:
  - the axis-aligned bbox
  - another 4-point geometry block before the text payload
- That 4-point block is currently the best candidate for “missing layout geometry” behind the
  rotated text-box bug.

## Best Next RE Direction

Without creating new samples yet:

- Compare the full rotated (`16°`, `90°`) text-box blobs against each other around:
  - the longer header region (`121..141`)
  - the bytes between header end and `text_off`, especially the shifted `f64` block beginning at
    `header_total + 0x12`
  - any stable offsets that differ while text content/styling differences are accounted for
- Use `--layout-debug` only as the current renderer hypothesis, not as truth.
