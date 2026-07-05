# Format Coverage Report

Snapshot for the current `pysdocx` parser/renderer state on branch `feat/web-viewer`:

```text
d98881a feat(pysdocx): expose pen style tail params
```

This report answers a specific question:

> How much of the Samsung Notes `.sdocx` format are we treating structurally, and how much is still
> partial / inferred / heuristic / unknown?

It is intentionally about **format knowledge**, not just visible rendering quality.

Companion artifacts:

- [`FORMAT-PROFILES.md`](./FORMAT-PROFILES.md): compact human-readable family/profile summary
- [`FORMAT-COVERAGE-INVENTORY.json`](./FORMAT-COVERAGE-INVENTORY.json): machine-readable inventory
- `.venv/bin/python -m pysdocx inventory [paths...] [--json]`: regenerate the current corpus view

## Coverage Levels

Use these labels consistently:

- `Structural`
  - We know the container/record/object boundaries deterministically.
  - Example: `.page` layer/object tree, object header fields, object `blob_size`.
- `Semantic`
  - We know what a field/block *means* well enough to expose it as data, not just skip over it.
  - Example: typed-text paragraph alignment, stroke pressure, text-box angle.
- `Marker / Inferred`
  - We identify content by signatures, consistency checks, or payload markers, but do not yet have
    a full field-by-field semantic model.
  - Example: sticky-note placements outside the declared object count, some image/drawing scans.
- `Heuristic`
  - The behaviour is calibrated against samples or GT, but is not yet a decoded property of the
    file format itself.
  - Example: typed-text pagination target page, some renderer geometry constants.
- `Unknown`
  - Bytes/fields/behaviour that are present but not yet explained.

## Executive Summary

The current parser is already **structural at the page/layer/object level**.

Compared with the research style in [`samsung-notes-format`](../samsung-notes-format/README.md),
`pysdocx` is no longer a flat stroke reader. It reads:

- container members
- page order
- page header
- layer list
- object entries with exact boundaries
- common object header
- type-specific payloads for the object families seen in the current sample corpus

That means the weakest part of the project is **not** “we don't know where the objects are”.
The weaker part is:

- some object payload semantics are only partially decoded
- some object families are located/used by markers rather than fully specified field schemas
- renderer behaviour still includes heuristics layered on top of decoded structure

## Object Coverage In Current Sample Corpus

Observed across the current `samples/*.sdocx` corpus:

```text
OBJECT TYPES Counter({'stroke': 11375, 'shape': 390, 'image': 15, 'text_box': 7, 'drawing': 1})
RAW TYPES    Counter({1: 11375, 7: 337, 8: 53, 3: 15, 2: 7, 14: 1})
```

Implication:

- For the current sample corpus, we are already classifying **all observed object types** in the
  page tree.
- We do **not** currently have a backlog of “raw object types seen but totally unclassified”.

This is strong evidence that the project is structurally sound at the object-tree level.

## Coverage Matrix

### 1. ZIP Container

Files:

- `pageIdInfo.dat`
- `note.note`
- `<uuid>.page`
- `media/*`
- `end_tag.bin`

Status:

- `pageIdInfo.dat`: `Structural + Semantic`
  - true page order decoded and used by [`container.py`](../pysdocx/container.py)
- `note.note`: `Structural`, partially `Semantic`
  - loaded deterministically
  - typed rich text, tables, top-level metadata, and part of the tail records decoded
  - `tail_hash_block` now linked structurally to the `pageIdInfo.dat` head
  - current tail record boundaries are structurally covered on the sample corpus; raw prelude/style/audio
    tail fields are surfaced as inventory diagnostics where their semantics are not yet stable
- `.page`: `Structural`, partially `Semantic`
  - parsed as layer/object tree
- `media/mediaInfo.dat`: `Structural + Semantic`
  - manifest header/count, record boundaries, media index, filename, SHA-256, and `EOFX` decoded
  - current corpus: 60/60 manifest records point to existing media files and SHA-256 verification passes
- `media/*`: `Structural`, partially `Semantic`
  - attachments enumerated, raster media recognized, manifest metadata attached where present
- `end_tag.bin`: `Known but effectively unused`

What is still missing:

- no full semantic decode of `end_tag.bin`
- no full semantic decode of the raw `note.note` tail fields around pen preload/style/audio metadata
- no semantic decode of the 11-byte raw per-record tail inside `mediaInfo.dat`

### 2. Page Header

In [`page.py`](../pysdocx/page.py):

- `base`
- page width / height
- page UUID
- content bounding box
- template id

Status:

- `Structural + Semantic`

What is still missing:

- some header-dependent template semantics beyond the currently known grid ids

### 3. Layer / Object Tree

In [`page.py`](../pysdocx/page.py):

- layer count
- current layer index
- layer flags/content flags
- layer UUID / modified time when present
- object count
- object entry boundaries
- child recursion

Status:

- `Structural`

What is still missing:

- full semantics of all layer flags / content flags
- full semantics of all common object-header flags / field flags

### 4. Common Object Header

Decoded fields:

- total header size
- data type
- variable data offset
- flags / field flags
- format version
- object UUID
- modified time
- bbox
- timestamp
- resizable
- decoded `field_flags` size model:
  - `0x1` rotation angle f32
  - `0x20` `extra_key_stroke_shape` block
  - `0x40000` 16-byte header extension
  - `0x8000` media/shape family bit
  - `0x2000|0x4000` base-present bits

Status:

- `Structural`
- selected fields are `Semantic`

Examples of semantic use:

- bbox used for geometry validation and placement
- field flag bit `0x1` used to trust angle f32 for rotated objects
- `0x20` block decoded as `extra_key_stroke_shape` on 40/40 objects
- `0x40000` extension page dimensions match 1690/1690 objects

What is still missing:

- exact semantic of the object-header `flags` u16
- exact semantic of `ext_block.counter` and `ext_block.seq`

### 5. Stroke Objects

Status:

- `Structural + Semantic`

Decoded well:

- stroke object selection from raw type `1`
- alternate payload layouts
- coordinate delta decode
- trailing channels
- pressure
- intensity
- pen width
- color
- tool family / taperedness

This is the part closest in spirit to `samsung-notes-format`, but expanded beyond pure geometry.

### 6. Shape Objects

Status:

- object membership: `Structural`
- visual geometry: largely `Semantic`
- some internals: still `Marker / Inferred`

Decoded/used:

- type classification
- outline geometry
- closed/open handling
- width/color
- arrows / freeform / regular shapes

What is still missing:

- complete formal schema for every shape payload variant

### 7. Image Objects

Status:

- object membership: `Structural`
- placement/rotation/media ref: `Semantic`
- some media-link details: still `Marker / Inferred`

Decoded/used:

- image placement bbox
- media index
- rotation angle

### 8. Drawing Objects

Status:

- object membership: `Structural`
- media linkage / placement: `Marker / Inferred`

Decoded/used:

- drawing media placement from object/blob markers
- raster drawing rendering when media is raster

What is still missing:

- fuller object-level semantics for drawing payloads

### 9. Text Box Objects

Status:

- object membership: `Structural`
- text/rich text/angle: `Semantic`
- rotated frame geometry: now largely `Semantic`
- inner text layout model: still partial

Decoded/used:

- text content
- local style runs
- colors / highlights / font sizes
- rotation angle
- `frame_midpoints` for rotated boxes

What is still missing:

- whether Samsung stores a smaller inner text frame / padding
- whether there are additional text-flow/layout fields beyond geometry + rich-text runs

### 10. Sticky Notes / Audio / Other Attachments

Status:

- archive attachment enumeration: `Structural`
- kind classification: `Semantic`
- sticky-note page property bags: `Structural + Semantic`
- non-sticky attachment placement: still `Marker / Inferred`

Decoded/used:

- attachment listing from `media/*`
- sticky-note attachment-property bags from page bytes
- media index / attachment type-tag / bag keys / collapse bbox

What is still missing:

- a structural page-object model for attachment placement in all cases
- full rendering / recursive decode of nested sticky-note `.sdocx`
- explicit page-level structure for audio placements where object trees are empty

### 11. note.note Typed Text

Status:

- text field selection: `Semantic`
- styling/paragaph metadata: `Semantic`
- page placement in the render: still partly `Heuristic`

Decoded/used:

- body text field with length-header validation
- bold / italic / underline / strike
- color / highlight / font sizes
- paragraph alignment / indent / line spacing
- heading/body styles
- space-before / space-after
- numbered / bullet / todo metadata

What is still missing:

- full note.note schema outside the typed-text, table, title, voice-clip, and tail-marker areas
- semantic explanation of the remaining note-level metadata flags/blocks

### 11a. note.note Tail Records

Status:

- tail boundary: `Structural`
- sentinel/hash/preload/voice markers: partially `Semantic`
- remaining gaps: `Unknown`

Decoded/used:

- `tail_sentinel` starts at `offset_to_data` on all current samples
- `tail_hash_block` appears once per sample and is linked to the `pageIdInfo.dat` head
- `pen_preload_path` is decoded as `u16 char_len + UTF-16LE path` (38 paths across the corpus)
- `pen_preload_prelude` / `pen_preload_prelude_raw` classify the small bounded blocks before paths
- `pen_style_tail` classifies recurring pen-style blocks with a leading f32 width + ARGB color
  and an optional digit/semicolon parameter string
- preload `param_hint` strings are recorded conservatively when adjacent (`8;`, `14;`, `18;0;100;`)
- localized voice labels are accepted as `Voice N` or `Voce N`
- inventory reports known/unknown tail-byte coverage

Current corpus measurement:

- known tail bytes: `5938`
- unknown tail bytes: `0`
- known ratio: `100%`
- hash prefixes: `[2, 2]` on 10 samples, `[0, 2]` on 3 samples

What is still missing:

- exact semantics of the raw fields around preload paths
- exact meaning of preload parameter hints
- exact meaning of `pen_style_tail.param` and `pen_style_tail.raw_u32`
- exact meaning of the 4-byte trailing values after some hash blocks
- exact semantics of `voice_clip.post_u32`

### 12. note.note Tables

Status:

- `Marker / Inferred` to `Semantic`

Decoded/used:

- cell texts
- grid reconstruction
- basic cell rich text

What is still missing:

- a complete schema-level understanding of every table-related block

## What We Currently Ignore Entirely vs Partially

### Largely Ignored / Not Yet First-Class

- `end_tag.bin` semantics
- most object-header flag meanings
- most layer/content flag meanings
- attachment/page linkage for all non-image attachment families
- full nested sticky-note sub-document render pipeline
- full note.note schema beyond typed text + tables + bg color

### Partially Used But Not Fully Explained

- `mediaInfo.dat` per-record raw tail fields
- shape payload variants
- drawing payload details
- text-box inner layout model
- image media-link details beyond what is needed to place/render them

## Where We Are Strongly Structural

These are the areas where “vibecoding fear” should be lower:

- page ordering from `pageIdInfo.dat`
- `.page` layer/object tree
- object boundaries via stored size
- object-family classification in current sample corpus
- stroke payload decode
- typed-text rich text and paragraph metadata
- text-box rich text and rotation

## Where We Are Still Vulnerable To False Confidence

These are the areas where visible success may hide incomplete format knowledge:

- renderer page-placement heuristics for note-level typed text
- text-box inner text layout
- attachment placement when no object-tree entry exists
- semantics of unknown flag bits
- any feature whose current implementation depends on scanning arbitrary bytes for markers

## Relation To `samsung-notes-format`

`[samsung-notes-format](../samsung-notes-format/)` is structurally very clean, but intentionally
focused on page/stroke decoding.

Current `pysdocx` status:

- matches that “layer/object” mindset structurally
- goes significantly further in content coverage
- is therefore *less minimal* but *more complete*

So the honest framing is:

- we are already structural on the outer format
- we are not yet exhaustive on inner object semantics

## Best Next Steps If The Goal Is “More True Format Knowledge”

High-value directions, ordered by likely knowledge gain:

1. Explain `ext_block.counter` / `ext_block.seq` if future samples expose a cleaner correlation.
2. Fully model the rotated text-box inner layout using the newly decoded frame geometry.
3. Turn attachment placement (sticky/audio) from byte-scan discovery into a structural object/path model.
4. Expand `note.note` coverage beyond typed text/tables/top-level metadata/voice clips.
5. Make a compact machine-readable inventory of decoded fields vs unknown fields per object family.

## Bottom Line

If the question is:

> “Are we still mostly guessing?”

The answer is:

- **No** at the container/page/object-tree level.
- **Partly yes** inside some object payload semantics.

If the question is:

> “How structural are we today?”

The best short answer is:

- **Structurally strong on file layout and object membership**
- **Semantically strong on strokes, typed text, and basic text boxes**
- **Still incomplete on deeper payload semantics and some non-visual attachments**
