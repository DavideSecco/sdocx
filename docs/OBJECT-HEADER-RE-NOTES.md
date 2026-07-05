# Object-Header `field_flags` + note.note `meta_flags` RE Notes

Checkpoint gathered on top of branch state:

```text
febc3cd feat(pysdocx): heading spacing and typed-text pagination
```

This round decoded the previously-unexplained flag bits that `pysdocx inventory` had bucketed as
`unknown_bits`, using pure **corpus-wide correlation** over the existing 13 `samples/*.sdocx` — no new
samples, no renderer changes. A bit is only promoted to a decoded feature when it correlates **totally**
(zero counterexamples) with an observable structure across the whole corpus.

## Track A — common object-header `field_flags`

### Signatures observed

```
type      total_size  field_flags   count
stroke    121         0x6000        9921     (base)
stroke    137         0x46000       1414
stroke    153         0x6020        8
stroke    157         0x6021        19
stroke    169         0x46020       8
stroke    173         0x46021       5
text_box  121         0x6000        3        (base)
text_box  141         0x46001       4
image     122         0xe000        7
image     142         0x4e001       8
shape     122         0xe000        139
shape     138         0x4e000       251
drawing   122         0xe000        1
```

### The size model is fully additive (zero counterexamples)

Baseline `total_size` is **121** for stroke/text_box and **122** for the image/shape/drawing family.
Every signature above reconstructs from baseline plus a fixed per-bit byte contribution:

| bit       | name (decoded)        | size delta | evidence |
|-----------|-----------------------|------------|----------|
| `0x1`     | rotation angle f32    | +4         | f32 at offset 105, already cracked for images |
| `0x20`    | `extra_key_stroke_shape` block | +32 | named attribute block, key string decoded verbatim, 40/40 |
| `0x40000` | 16-byte header ext    | +16        | see below; trailing width/height match page 1690/1690 |
| `0x8000`  | media/shape family    | (none)     | set on all image/shape/drawing, on no stroke/text_box |
| `0x2000`  | base "present" bit    | (none)     | set on every object |
| `0x4000`  | base "present" bit    | (none)     | set on every object |

Worked examples:

- stroke `0x46021` = 121 + 16(`0x40000`) + 32(`0x20`) + 4(`0x1`) = **173** ✓
- stroke `0x6020`  = 121 + 32(`0x20`) = **153** ✓
- image  `0x4e001` = 122 + 16(`0x40000`) + 4(`0x1`) = **142** ✓
- shape  `0x4e000` = 122 + 16(`0x40000`) = **138** ✓

Because these deltas are independent (there are strokes with `0x20` but not `0x40000`, and with `0x1`
but not `0x40000`), each bit's contribution is isolated rather than inferred from a single combined case.

### `0x40000` header extension (16 bytes)

Layout, little-endian:

```
[u32 counter] [u32 note_value] [u32 page_width] [u32 page_height]
```

- **page_width / page_height** equal the page header's dimensions on **1690/1690** objects. This includes
  the 13 objects where the extension is shifted by the preceding `0x20` `extra_key` block. The corpus has
  4 distinct page sizes (`1600x2262`, `1080x27952`, `1812x15372`, `1848x7838`), so this match is a real
  signal, not a coincidence.
- **counter** is a large value that **repeats within some files**, so it is **not** a unique per-object id.
  Repeated counters often group related objects: in `Allsamsungnotes`, every repeated-counter group is
  consecutive, same-page, same-type strokes; in the shape samples, many counters repeat across duplicated
  pages / copied shape families (and even across the old/new shape files). This looks like a stable object
  lineage/group id, but it is not yet a clean semantic.
- **seq** is a small value around `415072..415139` that is **near-constant within a note** and only bumps
  occasionally. It is not per-object and not reliably monotonic in object order (`OnlyShapesblack*` has 3
  inversions). It reads as a save/session/app-global value, but exact origin is unresolved. Named `seq` in
  `ext_block`.

Decoded in [`page.py`](../pysdocx/page.py) `_decode_header_ext()` and exposed as `header["ext_block"]`.

### `0x20` `extra_key_stroke_shape` block (32 bytes)

Fully readable. After the header (offset 105, +4 if a rotation angle precedes it) the block is:

```
[02 01 00]            constant 3-byte head
[17 00]               u16 length = 23
["extra_key_stroke_shape\0"]   the 23-byte key string (22 chars + NUL)
[01 00 00 00][u32]    trailing value(s)
```

The key string is **identical on all 40/40** objects that set `0x20`, and the bit only ever appears on
stroke objects — so `0x20` marks a **stroke that is a shape's ink** (`extra_key_stroke_shape`). Promoted as
the `extra_key_stroke_shape` feature. Decoded in [`page.py`](../pysdocx/page.py) as
`header["extra_key_block"] = {off, head, head_ok, key_len, key, trailing}`; corpus check after promotion:
**40/40** blocks have `head=020100`, `key_len=23`, `key="extra_key_stroke_shape"`, `trailing=1`.
The trailing value is not yet interpreted (flag-vs-count cannot be disambiguated because it never varies).

### Object-header `flags` field (the field before `field_flags`)

Separate `u16` `flags` field (always `flag_len == 2`). Observed values:

- image / shape / drawing / text_box: **always `0x1bf`** (a constant capability field in this corpus).
- stroke: `0x1be` or `0x1bf` — only bit `0x1` varies.

The stroke `0x1` bit is an **invariant, not yet a clean semantic**: it is set on 100% of extended-header
strokes (any object with an extra field_flags bit) and on 0% of them is it unset; among plain base strokes
it still splits (2812 set / 7109 unset). Joined to the parsed strokes, `flags 0x1 == 0` implies a basic
pen (`tool_id ∈ {0,1}`) with a longer average path (≈129 pts), while `flags 0x1 == 1` covers every
non-basic tool (`tool_id 2/3/4/6`) plus many basic strokes (≈67 pts avg). So it correlates with — but is
not determined by — tool complexity. Left documented as an invariant, not promoted to a decoded flag.

### Ordering caveat

When an object sets **both** `0x20` and `0x40000`, the `extra_key` block is stored first (lower in
`total_size` order), so the 16-byte extension no longer sits at the plain `OBJECT_BASE_HEADER_LEN`
offset. `_decode_header_ext()` now adds `EXTRA_KEY_BLOCK_LEN` in that case; the shifted decode accounts
for the remaining 13 objects and raises the clean page-dimension match from 1677/1677 to 1690/1690.

### Result

`_object_header_profile().unknown_bits` is now **empty across the entire corpus** — every observed
`field_flags` bit has a decoded meaning. Any future sample that sets a novel bit will surface it in
`unknown_bits` immediately (the promotion is a positive allow-list, not a blanket suppression).

## Track B — note.note `meta_flags`

`meta_flags` values seen: `0xc8e80` (handwriting, fmt4000), `0xc0a80` (typed, fmt5400),
`0xcae80` (typed+tables+preload), `0xc2a80` (typed+tables+voice).

Correlating each bit against the independently-parsed observables (`typed_text`, `tables`, `voice`,
`format_version`, `pen_preload`):

- **`0x2000` = has-tables.** Set on exactly the 2 table-bearing notes and on no other note (including
  typed-but-tableless ones), and it agrees with the parsed table cells. **Promoted** to
  `meta_tables_flag_0x2000` in [`inventory.py`](../pysdocx/inventory.py) `_note_profile()`.
- `0x80 | 0x200 | 0x800 | 0x40000 | 0x80000` are set on **every** note → base "present" bits
  (`meta_base_bits`).
- `0x400` and `0x8000` vary (10/13 each) but co-vary with each other and do **not** line up with any
  observable feature (e.g. one typed note sets them, another typed note does not) → kept **unknown**.
- `flags` bit `0x8` is set on 10/13 with no clean feature split (mixed within fmt4000) → kept **unknown**.

`format_version`, `typed`, and `voice` are NOT single-bit features in `meta_flags` (no bit uniquely marks
them across the corpus), so they are left as derived observables rather than decoded flag bits.

## What did NOT resolve

- The semantic meaning of the `0x20` `extra_key` trailing u32 (`1` on 40/40 objects).
- The exact meaning of `seq` / `counter` in the header extension.
- `meta_flags` `0x400`/`0x8000` and `flags` `0x8`.
- These all need either more samples or a cross-field correlation this corpus can't provide.
