# `.page` → common object header

Every object in the layer/object tree begins with a common header. Its base is a
fixed layout; its length grows by an **additive `field_flags` model** that is
fully decoded (zero counterexamples across the corpus). This is some of the most
strongly-grounded RE in the project.

- **Formal spec:** [`spec/ksy/sdocx_object_header.ksy`](../../../../spec/ksy/sdocx_object_header.ksy)
  — fed one object blob; models the base header **and** the field_flags-gated
  extensions. Validated field-by-field against pysdocx on **11788/11788** corpus
  objects by the test gate.
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

### `0x20` EXTRA_KEY — 32-byte named block
A `u16`-length-prefixed key string after a constant `02 01 00` head. The key is
literally `extra_key_stroke_shape` (23 chars), then a trailing `u32 = 1`.
Identical on **40/40** objects that set the bit, and only on **strokes**.
Interpretation: the stroke is a shape's recognised ink. Honest caveat: despite
the name these strokes do **not** link to any inserted-shape object (shapes = 0
on every page carrying them), so it reads as a per-stroke attribute, not a
foreign key.

### `0x40000` HDR_EXT — 16-byte extension
Layout `[u32 counter][u32 seq][u32 page_width][u32 page_height]`. The trailing
`page_width`/`page_height` match the page header on **1690/1690** objects (across
4 distinct page sizes — real signal).

## Unknown

- **`flags` (the u16 before `field_flags`)** — constant `0x1bf` on non-stroke
  objects; on strokes only bit `0x1` varies (an invariant: every extended-header
  stroke sets it), but it does not split cleanly enough to name → documented, not
  promoted.
- **`ext_block.seq` / `ext_block.counter`** — `seq` is near-constant within a
  note (not per-object, not always monotonic); `counter` repeats and often groups
  related/copied objects. No clean semantic yet.
- **`extra_key` trailing `u32 = 1`** — decoded as constant; flag-vs-count can't
  be disambiguated because it never varies.
