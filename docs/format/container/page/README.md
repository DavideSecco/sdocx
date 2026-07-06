# `<uuid>.page`

One per page. Carries the page header (dimensions, UUID, content bounding box)
followed by a **layer/object tree** holding all the per-page graphics: ink
strokes, shapes, images, drawings, and in-page text boxes.

- **Formal spec (header):** [`spec/ksy/sdocx_page.ksy`](../../../../spec/ksy/sdocx_page.ksy)
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
```

On empty pages `content_bbox` is left uninitialised (NaN + denormals); that is
the source data, not a parse error.

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
```

Compares `base`, `page_width`, `page_height`, `uuid`, and `content_bbox`
(bytewise, to survive NaN) against `parse_page` on every `.page` in the corpus.
