# Format Profiles

Compact corpus-derived profiles from:

```bash
.venv/bin/python -m pysdocx inventory
```

Machine-readable companion:

- [`docs/FORMAT-COVERAGE-INVENTORY.json`](./FORMAT-COVERAGE-INVENTORY.json)

## Why This Exists

The project had already reached a good structural level, but some knowledge was still scattered
between code comments, ad-hoc shell probes, and GT-driven renderer work.

This file turns the repeated patterns into explicit profiles:

- common object-header families
- top-level `note.note` families
- page-level attachment property-bag families

These profiles are still descriptive, not final semantics. They help answer:

> “What parts of the format are stable enough that we can treat them as first-class structure?”

## 1. Common Object-Header Families

Observed across the current `samples/*.sdocx` corpus:

| Object type | Signature | Count | Current interpretation |
| --- | --- | ---: | --- |
| `stroke` | `121/0x6000` | 9921 | Base stroke header/payload family |
| `stroke` | `137/0x46000` | 1414 | Extended stroke family |
| `stroke` | `153/0x6020` | 8 | Extended stroke variant |
| `stroke` | `157/0x6021` | 19 | Extended rotated/special stroke variant |
| `stroke` | `169/0x46020` | 8 | Extended stroke variant |
| `stroke` | `173/0x46021` | 5 | Extended rotated/special stroke variant |
| `shape` | `122/0xe000` | 139 | One shape family |
| `shape` | `138/0x4e000` | 251 | Extended shape family |
| `image` | `122/0xe000` | 7 | Unrotated image family |
| `image` | `142/0x4e001` | 8 | Rotated image family |
| `drawing` | `122/0xe000` | 1 | Same header family as unrotated image/shape subset |
| `text_box` | `121/0x6000` | 3 | Unrotated text-box family |
| `text_box` | `141/0x46001` | 4 | Rotated text-box family |

### Stable facts

- `field_flags & 0x1`: angle `f32` present at object-header offset `105`.
- `field_flags & 0x20`: 32-byte `extra_key_stroke_shape` block. All 40/40 decoded blocks have
  `head=020100`, `key_len=23`, `key="extra_key_stroke_shape"`, `trailing=1`.
- `field_flags & 0x40000`: 16-byte header extension
  `[u32 counter][u32 seq][u32 page_width][u32 page_height]`; page dimensions match 1690/1690,
  including the shifted cases where `0x20` is also present.
- `field_flags & 0x8000`: media/shape family discriminator; set on all image/shape/drawing objects and
  on no stroke/text-box objects in the current corpus.
- `field_flags & (0x2000|0x4000)`: base-present bits set on every object seen so far.
- The rotated families for `image` and `text_box` line up exactly with `0x1`:
  - `image`: `122/0xe000` -> `142/0x4e001`
  - `text_box`: `121/0x6000` -> `141/0x46001`
- Common header `flags` are even tighter than expected:
  - `0x1bf` appears on every non-legacy object family in the current corpus
  - `0x1be` appears only on the large base-stroke-only handwritten files (`cs61bl`, `handwritten`, `quiz`)
  - this is a stable corpus distinction, but not yet a decoded semantic bit meaning

### Header extension caution

- `seq` is near-constant within a note and not per-object; in the shape samples it is not even strictly
  monotonic in object order.
- `counter` is not a unique object id. It can repeat within a file and often groups related objects
  (consecutive strokes, copied/duplicated shape families), but the exact semantic is unresolved.
- The trailing u32 in `extra_key_stroke_shape` is always `1` in the current corpus; flag-vs-count is not
  distinguishable yet.

## 2. note.note Families

Observed top-level signatures:

| Family | Signature | Count | Notes |
| --- | --- | ---: | --- |
| `v4000` | `fmt4000/flags0x0/meta0xc8e80` | 3 | Legacy/older note family, no non-empty typed text in corpus |
| `v4000` | `fmt4000/flags0x8/meta0xc8e80` | 6 | Same `meta_flags`, extra top-level flag bit `0x8` |
| `v5400_typed` | `fmt5400/flags0x8/meta0xc0a80` | 2 | Typed-text notes |
| `v5400_typed_tables` | `fmt5400/flags0x8/meta0xcae80` | 1 | Typed text + tables |
| `v5400_typed_tables_voice_hash` | `fmt5400/flags0x8/meta0xc2a80` | 1 | Typed text + tables + voice clip + shifted pageIdInfo tail block |

### Stable facts

- Top-level note metadata is now structural:
  - `format_version`
  - `flags`
  - `meta_flags`
  - `created_time`
  - `modified_time`
  - `width`
  - `height`
  - `page_h_padding`
  - `page_v_padding`
  - `min_format_version`
  - `title_size`
  - title extraction
- The current corpus strongly suggests distinct `v5400` subfamilies:
  - typed only
  - typed + tables
  - typed + tables + voice clip
- The voice-clip sample contains a recoverable subrecord:
  - label `Voice 001`
  - duration `00:00:12`
- The note tail is now partially classified:
  - `tail_sentinel` on every current sample
  - `pen_preload_path` on most `v4000` files and one mixed `v5400` sample
  - `tail_hash_block` on every current family
  - `voice_clip` only on the audio sample

### Important caveat

The inventory treats `typed_text_present` as **non-empty body text only**.

That matters because some `v4000` files can yield an empty typed-text parse candidate; those are
now treated as “no typed text” for profile purposes, which is the more honest interpretation.

### Tail records

Current tail-record kinds seen by the parser:

| Kind | Count | Interpretation |
| --- | ---: | --- |
| `tail_sentinel` | 13 | Stable marker at `offset_to_data` |
| `pen_preload_path` | 38 | Length-prefixed pen preload/config resource path strings |
| `tail_hash_block` | 13 | Opaque 32-byte hash-like block after the tail sentinel |
| `voice_clip` | 1 | Voice label/duration record in the audio sample |

`pen_preload_path` is now decoded as `u16 char_len + UTF-16LE path` rather than as a null-terminated
UTF-16 run. That fixes the earlier false leading slash and avoids swallowing printable-looking binary
bytes after paths such as `InkPen2`. The inventory also records the nearest digit/semicolon parameter
hints observed in this corpus: `8;` (6), `14;` (1), `18;0;100;` (1).

This is still partial structure, but it is already much better than treating everything after
`offset_to_data` as opaque mystery bytes: current known tail-byte coverage is `4594/5938` bytes
(`77.37%`) across the 13-sample corpus.

### pageIdInfo relation

The `tail_hash_block` is no longer just “hash-like”; it has a stable container-level relation:

- `10/13` current samples:
  - the block payload matches the first 32 bytes of `pageIdInfo.dat` exactly
  - these are the `[2, 2]` prefix cases
- `3/13` current samples:
  - the block payload is `u32(2)` + the first 28 bytes of that same `pageIdInfo.dat` head
  - these are the `[0, 2]` prefix cases
  - observed on:
    - `OnlyTextTypeWritten`
    - `OnlyTextTypeWritten_squared`
    - `Associationpages&stickynote&images&audio`

So the best current interpretation is:

- this tail block is a **pageIdInfo-head-derived reference block**
- its exact semantics are still incomplete
- but it is no longer fair to call it purely opaque

## 3. Attachment Property-Bag Families

Observed page-level attachment bag keys:

| Kind | Keys | Count |
| --- | --- | ---: |
| `sticky_note` | `co_attach_file`, `skn_bg_color`, `skn_collapse_rect` | 3 |

### Stable facts

- Sticky-note placements are not part of the declared page object count in the current sample set.
- Once located, they decode cleanly as a small property bag:
  - `co_attach_file`
  - `skn_bg_color`
  - `skn_collapse_rect`
- `co_attach_file` carries:
  - media index
  - following type tag (observed `2`)
- `skn_collapse_rect` carries the placement bbox as CSV text.

### Still missing

- A comparable page-level structural placement record for audio.
- A generalized attachment-placement model beyond the sticky-note bag family.
- Any trustworthy link from the `voice_clip` tail record to `media/12@...m4a`.

At the current stage, the audio sample does expose a `voice_clip` record in `note.note`, but no
direct media-index/file-name linkage has been recovered yet.

## 4. What This Changes Strategically

Compared with the earlier state, we can now say more confidently:

- the page/object side is not “mostly guessed”
- `note.note` is no longer just “typed text plus mystery bytes”
- attachment placement has at least one real structural family, even if audio still does not
  resolve structurally

The highest-value next RE direction remains:

1. turn header profiles into fuller bit semantics
2. explain more of the `note.note` top-level/profile differences
3. find whether audio placement exists in a page structure analogous to the sticky-note bag, or
   whether it only survives as note-level metadata in the current corpus
