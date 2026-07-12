# `.page` → common object header

Every object in the layer/object tree begins with a common header. Its base is a
fixed layout; its length grows by an **additive `field_flags` model** that is
fully decoded (zero counterexamples across the corpus). This is some of the most
strongly-grounded RE in the project.

- **Formal spec:** [`spec/ksy/sdocx_object_header.ksy`](../../../../spec/ksy/sdocx_object_header.ksy)
  — fed one object blob; models the base header **and** the field_flags-gated
  extensions. Validated field-by-field against pysdocx on every corpus
  objects by the test gate.
- **HDR_EXT diagnostic:** [`spec/tools/analyze_header_ext.py`](../../../../spec/tools/analyze_header_ext.py)
  exports every 0x40000 extension row and summaries for `seq` / `counter`
  investigation.
- **Residual diagnostic:** [`spec/tools/analyze_object_header_residuals.py`](../../../../spec/tools/analyze_object_header_residuals.py)
  summarizes header `flags`, `extra_key.trailing`, and HDR_EXT residuals.
- **Reference parser:** `_parse_object_header`, `_decode_header_ext`,
  `_decode_extra_key_block`, `_object_header_profile` in
  [`pysdocx/page.py`](../../../../pysdocx/page.py).
- **Status:** base layout **Structural**; `field_flags` size model **Decoded**;
  a few residual fields **Unknown**.

## Base header — Structural

Offsets are within the object blob. The base header is `OBJECT_BASE_HEADER_LEN =
105` bytes and is variable-length only through the two length-prefixed flag
fields and the UTF-8 UUID:

```
0    u32   total_size          full header size (reconstructed by field_flags, below)
4    s16   data_type
6    u32   var_data_offset     offset to the object's variable/payload data
10   u8    flag_len            length of the flags field
11   ..    flags               little-endian, flag_len bytes
..   u8    field_len           length of the field_flags field
..   ..    field_flags         little-endian, field_len bytes  <-- size model below
..   u32   format_version
..   str   uuid                UTF-8, length-prefixed
..   s64   modified_time
..   32    bbox                4 x f64
..   u32   timestamp
..   u8    resizable
```

The bbox is used for geometry validation and object placement; `data_type` (raw
type) classifies the object (`1` = stroke, `2` = text_box, `3` = image, `7`/`8` =
shape, `14` = drawing).

## `field_flags` additive size model — Decoded

Every distinct `(total_size, field_flags)` signature in the corpus reconstructs
`total_size` **additively** from the bits below. Baseline `total_size` is `121`
for stroke/text_box and `122` for the image/shape/drawing family.

| bit | name | size delta | meaning |
|---|---|---|---|
| `0x1` | `ANGLE` | +4 | rotation-angle `f32` at offset 105 |
| `0x20` | `EXTRA_KEY` | +32 | a named attribute block (see below) |
| `0x40000` | `HDR_EXT` | +16 | a 16-byte header extension (see below) |
| `0x8000` | `MEDIA_FAMILY` | 0 | family discriminator (image/shape/drawing) |
| `0x2000` \| `0x4000` | `BASE_PRESENT` | 0 | set on every object ("record present") |

Worked examples: stroke `0x46021` = 121 + 16 + 32 + 4 = **173** ✓; image
`0x4e001` = 122 + 16 + 4 = **142** ✓. When both `0x20` and `0x40000` are set, the
16-byte extension sits **after** the 32-byte extra-key block (total-size-bit
order). Running `pysdocx inventory samples` reports `unknown_bits` **empty across
the whole corpus** — a novel bit in a future file would surface immediately.

### `0x1` ANGLE — rotation `f32` @ 105
A little-endian `f32` rotation angle in degrees (clockwise on screen) at the
common header's attributes offset (105). The bit gates it: on unrotated objects
that offset is other fields and reads as near-zero garbage. Verified against 9
hand-labelled rotated images (exact on 5/6 non-zero angles, 1° off on a
protractor-drawn label) and two `-45°/90°` placements.

### `0x20` EXTRA_KEY — variable-sized named property
The original form is a `u16`-length-prefixed key after a `02 01 00` head. Its
key is `extra_key_stroke_shape` (23 chars), followed by `u32 = 1`.
Interpretation: the stroke is a shape's recognised ink. Honest caveat: despite
the name these strokes do **not** link to any inserted-shape object (shapes = 0
on every page carrying them), so it reads as a per-stroke attribute, not a
foreign key.

`Mathsolver&Hyperlink` proves that the block is not fixed at 32 bytes. Math
Solver uses a `04 01 00` head with `RecogUIFeature_*` keys; the
`RecogUIFeature_MathStrokeUuidStringArray` value is `[u16 count]` followed by
counted UTF-16 strings. Their names and values identify them as stroke UUIDs
associated with the recognised expression (15 in the first observed group),
but the exact relationship remains Marker. A 16-byte zero tail
follows HDR_EXT on this family. Both Python and Kaitai decode the two property
forms and cross-check every string.

The same sample contains `06/07 01 00` multi-property chains, now decoded
byte-exactly in all 9 instances. `07` starts with
`RecogUIFeature_MathExpressionString = [u16 chars][UTF-16LE]`, followed by a
separator `u16 = 1`, `RecogUIFeature_MathFailCodeKey = u32`, then another
separator and `RecogUIFeature_MathStrokeUuidStringArray`. `06` is the same
chain without the expression: its outer property is the fail code, followed by
the UUID-array property. The four distinct observed payloads all close exactly;
the recognised expression strings include `A^{T}1k\\mid SOCUr=R`, and every
observed fail code is 7. The semantic meaning of code 7 remains Unknown.

### `0x40000` HDR_EXT — 16-byte extension
Layout `[u32 counter][u32 seq][u32 page_width][u32 page_height]`. The trailing
`page_width`/`page_height` match the page header on every corpus object carrying
the block, across multiple page sizes.

Diagnostic command:

```bash
.venv/bin/python spec/tools/analyze_header_ext.py samples
```

Current corpus summary:

- **0** HDR_EXT/page-dimension mismatches across the corpus.
- Object types carrying it: stroke 1427, shape 251, image 8, text_box 4.
- Extension offsets are explained by prior gated fields:
  - `105` when HDR_EXT starts immediately after the base header;
  - `109` when ANGLE precedes it;
  - `137` when EXTRA_KEY precedes it;
  - `141` when ANGLE + EXTRA_KEY precede it.
- `seq` is file/session-like, not object-like: usually one value per file, with
  small multi-value ranges on edited/copied notes (`415117..415119` on the
  shape sample family). It is not per-object and not equivalent to
  `file_revision`.
- `counter` is not unique: 276 repeated groups / 1029 objects. Repeats are
  meaningful, though: the two `OnlyShapesblack` samples share all 227 old
  counters; the later `OnlyShapesblack_new` sample has those plus 92 additional
  counters for the newly added page/content. This makes `counter` look like a
  persistent object/group lineage id, but the corpus still has mixed groups
  (shape+stroke) and repeated same-type groups, so the exact semantic is not
  promoted.

## Unknown

- **`flags` (the u16 before `field_flags`)** — constant `0x1bf` on non-stroke
  objects; on strokes only bit `0x1` varies. Corpus counts: `0x1be` on 7109
  stroke objects, `0x1bf` on 4266 stroke objects and all 413 non-stroke
  objects. Every extended-header stroke sets `0x1bf`; base stroke
  `121/0x6000` can be either `0x1be` or `0x1bf`. The split crosses tool/width
  families, so it is documented but not named.
- **`ext_block.seq` / `ext_block.counter`** — bounded and structurally decoded,
  but semantic names are deliberately withheld. `seq` behaves like a
  file/session save-generation value; `counter` behaves like a persistent
  object/group lineage id. Neither interpretation is clean enough for Decoded
  status on the current corpus.
- **Scalar `extra_key` trailing `u32 = 1`** — flag-vs-count remains ambiguous.
