# `<uuid>.page`

One per page. Carries the page header (dimensions, UUID, content bounding box)
followed by a **layer/object tree** holding all the per-page graphics: ink
strokes, shapes, images, drawings, and in-page text boxes.

- **Formal spec (header + layer/object tree):**
  [`spec/ksy/sdocx_page.ksy`](../../../../spec/ksy/sdocx_page.ksy)
  (validated on all 48 corpus pages — see [validation](#validation)).
- **Reference parser:** `parse_page` / `parse_page_tree` / `_parse_object_header`
  in [`pysdocx/page.py`](../../../../pysdocx/page.py).
- **Conventions:** [`../../00-conventions.md`](../../00-conventions.md).

## Sub-pages

| Topic | Nature | Page |
|---|---|---|
| Common object header + `field_flags` size model | **Decoded** | [`object-header.md`](./object-header.md) |
| Non-stroke payload-geometry wrapper | **Decoded** | [`payload-geometry.md`](./payload-geometry.md) |
| Stroke payloads (delta-compressed coords) | Marker / procedural | [`strokes.md`](./strokes.md) |
| Shapes / images / drawings / text boxes | mixed | [`object-types.md`](./object-types.md) |

## Page header — Decoded

Little-endian. Named fields hold with zero counterexamples across all 48 corpus
pages. Offsets are absolute in the `.page` member.

```
offset  size  field           status    note
0x00    4     base            Decoded   offset where the layer tree starts
0x16    4     page_width      Decoded
0x1a    4     page_height     Decoded
0x26    2     uuid_char_len   Decoded
0x28    ...   uuid            Decoded   UTF-16LE (= member filename, pageIdInfo)
0x80    32    content_bbox    Decoded   4 x f64 [x_min,y_min,x_max,y_max]
end-58  32    page_hash       Decoded   copied into pageIdInfo.dat (see below)
end-26  26    footer_signature Decoded  "Page for SAMSUNG S-Pen SDK"
```

On empty pages `content_bbox` is left uninitialised (NaN + denormals); that is
the source data, not a parse error.

### Page footer — Decoded

Every `.page` ends with a 32-byte page content hash immediately followed by the
ASCII signature `Page for SAMSUNG S-Pen SDK` (the per-page analog of
`end_tag.bin`'s `Document for S-Pen SDK`). That 32-byte hash is exactly what
[`pageIdInfo.dat`](../pageIdInfo.md#page_recordpage_hash--32-bytes--74--decoded-source-found)
stores as the page's `page_hash` — the manifest copies it. The test gate
cross-checks the two per page (48/48). Reference: `parse_page_footer` in
[`pysdocx/page.py`](../../../../pysdocx/page.py). How the page computes the hash
is still Unknown; the manifest↔page linkage is decoded.

### Paper (background) color — Decoded

Each page stores its **paper color** in the header preamble as a small record:

```
[u32 kind] [B G R 0xFF] [u32 display_width]
   kind ∈ {2, 3}         BGRA, alpha == 0xFF   device paper width (px)
```

The record's *absolute* offset varies with a variable-length header preamble
(seen at `0x84` / `0xa4` / `0x13e` / `0x15e`), so it is **located by that
signature** within `[0x7c, base)` rather than a fixed offset — the earlier
fixed-offset guess (`0x84`/`0x80`/`0xa4` keyed on `base`) misread `base==0x8c`
pages as having *no* paper. The signature yields exactly one match on all
**122 pages** of the 14-sample corpus **+** the 4 one-variable background samples
in [`samples/test-background/`](../../../../samples/test-background/) (zero
counterexamples). Reference: `page_background_color` in
[`crates/sdocx/src/page.rs`](../../../../crates/sdocx/src/page.rs).

The `test-background` samples pin the field: `Default` `(252,252,252)`, `Bianca`
`(230,230,230)`, and — decisively — **`Rosina` `(245,221,221)`** (a pink paper,
the only sample whose value is unmistakably a tint), all differing *only* in the
paper. Every corpus note carries a **single light paper across all its pages**
(mostly `(252,252,252)`), so `note.note` does **not** store this — the paper is a
per-`.page` field. What sets `kind` to 2 vs 3, and the full structure of the
variable preamble before the record, are **Unknown** (not needed to read the
color); a full header-preamble model in the `.ksy` is future work.

The **template** (grid vs plain, grid pitch) is *not* a single fixed field: its
offset depends on `base` and whether the note is built-in or an imported PDF, so
it is decoded procedurally (`page_template`) and documented with the object
types rather than modeled in the `.ksy`. Grid template ids and their per-id
pitches are corpus constants, not stored in the `.page`.

## Layer / object tree — Structural

Starting at `base`: `u16 layer_count`, `u16 current_layer_index`, then that many
layers. Each layer has a prefix, a next-offset, three flag bytes + a
`content_flags` byte, a `layer_flags` u32, then a set of **optional** fields
gated by `content_flags` bits:

| `content_flags` bit | Adds |
|---|---|
| `0x01` | 1 byte |
| `0x02` | 4 bytes |
| `0x04` | UTF-16 string (a UUID) |
| `0x08` | UTF-16 string → `layer_uuid` |
| `0x10` | `s64` modified time |
| `0x20` | 4 bytes |

Then `u32 object_count`, the objects themselves, and a 32-byte layer hash. Each
object entry stores its `raw_type`, child count, and **size**, so object
boundaries are deterministic — the parser walks the tree by stored sizes rather
than resyncing byte-by-byte (which is what lets mixed pages keep their
handwriting between non-stroke records).

This structure is now modeled in Kaitai as `SdocxPage.tree`. Each object entry
uses a substream of `blob_size` bytes, whose first bytes are parsed as the
common `sdocx_object_header`; semantic payload decoding remains procedural.

Current corpus layer invariants (48/48 pages):

- exactly one layer per page; `current_layer_index == 0`;
- `layer_prefix == 0x62`;
- flag triple `(flag1, flag2, flag3) == (1, 2, 1)`;
- `content_flags == 0x18`, so each layer carries `layer_uuid` and
  `modified_time` and none of the other optional fields;
- `layer_flags == 0`;
- every layer has a 32-byte hash after its object tree.

These are structural facts, not full semantics for the flag bits. Future
multi-layer samples are needed before naming `layer_flags` or the other
`content_flags` options.

### Object types in the corpus

```
OBJECT TYPES  stroke 11375 · shape 390 · image 15 · text_box 7 · drawing 1
RAW TYPES     1:11375 · 7:337 · 8:53 · 3:15 · 2:7 · 14:1
```

Every observed object type is classified — there is no backlog of "seen but
unclassified" object types on the current corpus.

## Validation

```bash
KSC_GEN=<scratch>/gen .venv/bin/python spec/tools/validate_page.py
# -> 48 matched, 0 mismatched, out of 48 pages
KSC_GEN=<scratch>/gen .venv/bin/python spec/tools/validate_page_tree.py
# -> 48 page trees matched, 0 mismatched, 11788 objects, out of 48 pages
```

The header validator compares `base`, `page_width`, `page_height`, `uuid`, and
`content_bbox` (bytewise, to survive NaN) against `parse_page`. The tree
validator compares layer counts, flags, optional-field boundaries, object entry
offsets (`off`, `blob_off`, `end`), raw type, child count, blob size, recursive
child order, and the 32-byte layer hash against `parse_page_tree`.
